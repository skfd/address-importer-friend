"""OSM API 0.6 client: OAuth2 PKCE + changeset lifecycle with crash-safe idempotency."""
import base64
import hashlib
import json
import os
import secrets
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests
from cryptography.fernet import Fernet

from . import audit, config as _config, db as _db, osm_export

_CONFIG = _config.load()

_AUTHORIZE = "/oauth2/authorize"
_TOKEN = "/oauth2/token"
_API = "/api/0.6"

SCOPES = "read_prefs write_api"


class OsmAuthError(Exception):
    pass


def _fernet() -> Fernet:
    key = _CONFIG.fernet_key
    if not key:
        raise OsmAuthError("FERNET_KEY not set in .env")
    return Fernet(key.encode() if isinstance(key, str) else key)


def _kv_set(key: str, value: str) -> None:
    conn = _db.connect()
    try:
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    finally:
        conn.close()


def _kv_get(key: str) -> str | None:
    conn = _db.connect()
    try:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def store_tokens(token_json: dict[str, Any]) -> None:
    blob = _fernet().encrypt(json.dumps(token_json).encode()).decode()
    _kv_set("osm_oauth_tokens", blob)
    _kv_set("osm_oauth_stored_at", datetime.now(timezone.utc).isoformat())


def load_tokens() -> dict[str, Any] | None:
    blob = _kv_get("osm_oauth_tokens")
    if not blob:
        return None
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except Exception:
        return None


def build_auth_url() -> tuple[str, str]:
    """Return (authorize_url, state). Also stores PKCE verifier in kv keyed by state."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    _kv_set(f"pkce:{state}", verifier)
    params = {
        "response_type": "code",
        "client_id": _CONFIG.osm_client_id,
        "redirect_uri": _CONFIG.osm_redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    qs = "&".join(f"{k}={requests.utils.quote(str(v), safe='')}" for k, v in params.items())
    return f"{_CONFIG.osm_api_base}{_AUTHORIZE}?{qs}", state


def exchange_code(code: str, state: str) -> None:
    verifier = _kv_get(f"pkce:{state}")
    if not verifier:
        raise OsmAuthError("Unknown OAuth state (PKCE verifier missing).")
    resp = requests.post(
        f"{_CONFIG.osm_api_base}{_TOKEN}",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _CONFIG.osm_redirect_uri,
            "client_id": _CONFIG.osm_client_id,
            "client_secret": _CONFIG.osm_client_secret,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    resp.raise_for_status()
    store_tokens(resp.json())
    audit.log(actor="oauth", event_type="OAUTH_TOKEN_REFRESHED", payload={"method": "exchange_code"})


def _refresh_tokens(tokens: dict) -> dict:
    rt = tokens.get("refresh_token")
    if not rt:
        raise OsmAuthError("No refresh_token available; re-authorize.")
    resp = requests.post(
        f"{_CONFIG.osm_api_base}{_TOKEN}",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": _CONFIG.osm_client_id,
            "client_secret": _CONFIG.osm_client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    new_tok = resp.json()
    store_tokens(new_tok)
    audit.log(actor="oauth", event_type="OAUTH_TOKEN_REFRESHED", payload={"method": "refresh"})
    return new_tok


def _request(method: str, path: str, **kwargs) -> requests.Response:
    tokens = load_tokens()
    if not tokens:
        raise OsmAuthError("Not authorized; visit /oauth/start first.")
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {tokens['access_token']}"

    for attempt in range(6):
        resp = requests.request(method, f"{_CONFIG.osm_api_base}{path}", headers=headers, timeout=120, **kwargs)
        if resp.status_code == 401:
            tokens = _refresh_tokens(tokens)
            headers["Authorization"] = f"Bearer {tokens['access_token']}"
            continue
        if resp.status_code in (429, 509):
            wait = min(2 ** attempt, 60)
            time.sleep(wait)
            continue
        return resp
    resp.raise_for_status()
    return resp


def find_changeset_by_client_token(client_token: str) -> int | None:
    """Look up a prior changeset we opened with this client_token tag. Used for crash recovery."""
    tokens = load_tokens()
    if not tokens:
        return None
    # OSM has no direct tag-search for changesets, so we scan recent user changesets.
    resp = _request("GET", f"{_API}/user/details.json")
    if resp.status_code != 200:
        return None
    uid = resp.json().get("user", {}).get("id")
    if not uid:
        return None
    r = _request("GET", f"{_API}/changesets", params={"user": uid})
    if r.status_code != 200:
        return None
    root = ET.fromstring(r.text)
    for cs in root.findall("changeset"):
        for tag in cs.findall("tag"):
            if tag.attrib.get("k") == "import:client_token" and tag.attrib.get("v") == client_token:
                return int(cs.attrib["id"])
    return None


def _create_changeset(run_id: int) -> int:
    payload = ET.Element("osm")
    cs = ET.SubElement(payload, "changeset")
    for k, v in osm_export.changeset_tags(run_id).items():
        ET.SubElement(cs, "tag", k=k, v=v)
    body = ET.tostring(payload, encoding="utf-8")
    r = _request("PUT", f"{_API}/changeset/create", data=body, headers={"Content-Type": "text/xml"})
    r.raise_for_status()
    return int(r.text.strip())


def _upload_diff(changeset_id: int, run_id: int) -> dict[int, int]:
    body = osm_export.osmchange_xml(run_id, changeset_id)
    r = _request("POST", f"{_API}/changeset/{changeset_id}/upload",
                 data=body, headers={"Content-Type": "text/xml"})
    if r.status_code != 200:
        raise RuntimeError(f"Upload failed: HTTP {r.status_code} {r.text[:500]}")
    root = ET.fromstring(r.text)
    mapping: dict[int, int] = {}
    for el in root.findall("node"):
        mapping[int(el.attrib["old_id"])] = int(el.attrib["new_id"])
    return mapping


def _close_changeset(changeset_id: int) -> None:
    _request("PUT", f"{_API}/changeset/{changeset_id}/close")


def upload(run_id: int) -> None:
    """Upload a run's APPROVED candidates via the OSM API. Idempotent under
    crash/Ctrl-C: client_token, once stored on the run, is reused on retry; if
    a changeset for that token already exists on the server, we adopt it."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        row = conn.execute(
            "SELECT name, upload_status, client_token, changeset_id "
            "FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"run {run_id} not found")
        if row["upload_status"] == "uploaded":
            return
        run_name = row["name"]
        client_token = row["client_token"]
        changeset_id = row["changeset_id"]
    finally:
        conn.close()

    # Drop candidates already uploaded by an overlapping tile before building
    # the changeset, so an address point in a tile overlap is created once,
    # then collapse same-address duplicates within this run to one node.
    osm_export.skip_cross_run_duplicates(run_id)
    osm_export.skip_intra_run_duplicates(run_id)

    if not client_token:
        client_token = osm_export._ensure_client_token(run_id)

    comment = _CONFIG.changeset_comment_template.format(run_name=run_name)

    # Crash recovery: if no local changeset_id yet but server has one tagged
    # with our client_token, adopt it instead of opening a duplicate.
    if changeset_id is None:
        existing = find_changeset_by_client_token(client_token)
        if existing:
            changeset_id = existing
        else:
            changeset_id = _create_changeset(run_id)

        conn = _db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE runs SET upload_mode='osm_api', changeset_id=?, upload_status='uploading' "
                "WHERE run_id=?",
                (changeset_id, run_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO changesets (changeset_id, run_id, opened_at, comment, status) "
                "VALUES (?, ?, ?, ?, 'open')",
                (changeset_id, run_id, now, comment),
            )
            audit.log(actor="osm_client", event_type="CHANGESET_OPENED",
                      run_id=run_id,
                      payload={"changeset_id": changeset_id, "comment": comment}, conn=conn)
            conn.execute("COMMIT")
        finally:
            conn.close()

    # Upload diff (idempotent enough: if server already has our nodes from a
    # prior attempt, a retry will 409; we surface that rather than auto-recover).
    try:
        mapping = _upload_diff(changeset_id, run_id)
    except Exception as e:
        conn = _db.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE runs SET upload_status='needs_attention', upload_error_msg=? "
                "WHERE run_id=?",
                (str(e)[:500], run_id),
            )
            audit.log(actor="osm_client", event_type="UPLOAD_FAILED",
                      run_id=run_id, payload={"error": str(e)[:500]}, conn=conn)
            conn.execute("COMMIT")
        finally:
            conn.close()
        raise

    # Apply diffResult mapping. Candidates whose local_node_id appears in
    # the mapping flip to UPLOADED with their osm_node_id filled in. Anything
    # still APPROVED with a local_node_id was sent but not acknowledged —
    # mark the run needs_attention and let the operator reconcile.
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for local_id, new_id in mapping.items():
            conn.execute(
                "UPDATE candidates SET osm_node_id=?, stage='UPLOADED', stage_updated_at=? "
                "WHERE run_id=? AND local_node_id=?",
                (new_id, now, run_id, local_id),
            )
        unmapped_rows = conn.execute(
            "SELECT local_node_id FROM candidates "
            "WHERE run_id=? AND stage='APPROVED' AND local_node_id IS NOT NULL",
            (run_id,),
        ).fetchall()
        unmapped = [int(r["local_node_id"]) for r in unmapped_rows]
        if unmapped:
            msg = f"partial upload: {len(unmapped)} of {len(unmapped) + len(mapping)} items unmapped"
            conn.execute(
                "UPDATE runs SET upload_status='needs_attention', upload_error_msg=? "
                "WHERE run_id=?",
                (msg, run_id),
            )
            audit.log(actor="osm_client", event_type="UPLOAD_PARTIAL",
                      run_id=run_id,
                      payload={"changeset_id": changeset_id,
                               "uploaded": len(mapping),
                               "unmapped_local_node_ids": unmapped}, conn=conn)
        else:
            conn.execute(
                "UPDATE runs SET upload_status='uploaded', uploaded_at=? WHERE run_id=?",
                (now, run_id),
            )
            audit.log(actor="osm_client", event_type="CHANGESET_UPLOADED",
                      run_id=run_id,
                      payload={"changeset_id": changeset_id, "count": len(mapping)}, conn=conn)
        conn.execute("COMMIT")
    finally:
        conn.close()

    _close_changeset(changeset_id)
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE changesets SET closed_at=?, status='closed' WHERE changeset_id=?", (now, changeset_id))
        audit.log(actor="osm_client", event_type="CHANGESET_CLOSED",
                  run_id=run_id, payload={"changeset_id": changeset_id}, conn=conn)
        conn.execute("COMMIT")
    finally:
        conn.close()


def mark_uploaded_externally(run_id: int) -> None:
    """Flip a run to upload_status='uploaded' for the JOSM-external path: the
    operator downloaded the .osm, uploaded it via JOSM, and is telling the
    system to consider it done. No changeset_id (we don't know what JOSM
    chose). All APPROVED candidates flip to UPLOADED."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        row = conn.execute(
            "SELECT upload_status, client_token FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"run {run_id} not found")
        if row["upload_status"] == "uploaded":
            return
    finally:
        conn.close()

    # Make sure the run has a client_token even after a JOSM-only upload, so
    # later auditing / cross-referencing can find the upload.
    osm_export._ensure_client_token(run_id)

    # The .osm the operator just uploaded via JOSM excluded cross-run and
    # intra-run duplicates (write_xml runs the same guards); re-run them here
    # so those rows land in SKIPPED rather than being swept into UPLOADED below.
    osm_export.skip_cross_run_duplicates(run_id)
    osm_export.skip_intra_run_duplicates(run_id)

    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE runs SET upload_mode='josm_xml', upload_status='uploaded', "
            "uploaded_at=? WHERE run_id=?",
            (now, run_id),
        )
        conn.execute(
            "UPDATE candidates SET stage='UPLOADED', stage_updated_at=? "
            "WHERE run_id=? AND stage='APPROVED'",
            (now, run_id),
        )
        audit.log(actor="operator", event_type="MARKED_UPLOADED_JOSM",
                  run_id=run_id, payload={}, conn=conn)
        conn.execute("COMMIT")
    finally:
        conn.close()
