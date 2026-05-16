"""Emit JOSM-compatible .osm XML and osmChange XML for a run's APPROVED candidates."""
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom

from . import audit, config as _config, db as _db

_CONFIG = _config.load()

STATIC_TAGS = {
    "source": "City of Toronto Open Data",
}


def _ensure_client_token(run_id: int) -> str:
    """Return the run's client_token, generating one if absent. Stable across
    retries so OSM-side idempotency lookup (find_changeset_by_client_token)
    keeps working."""
    conn = _db.connect()
    try:
        row = conn.execute("SELECT client_token FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ValueError(f"run {run_id} not found")
        if row["client_token"]:
            return row["client_token"]
        token = str(uuid.uuid4())
        conn.execute("UPDATE runs SET client_token=? WHERE run_id=?", (token, run_id))
        return token
    finally:
        conn.close()


def changeset_tags(run_id: int) -> dict[str, str]:
    """Per-run changeset-level tags (matches IMPORT_PROPOSAL.mediawiki § Tagging plan / Changeset tags).

    Used for both API uploads (applied to the changeset) and JOSM exports
    (embedded as a header comment so the operator can paste them into JOSM's
    upload dialog).
    """
    conn = _db.connect()
    try:
        row = conn.execute("SELECT name, client_token FROM runs WHERE run_id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise ValueError(f"run {run_id} not found")
    token = row["client_token"] or _ensure_client_token(run_id)
    comment = _CONFIG.changeset_comment_template.format(run_name=row["name"])
    return {
        "comment": comment,
        "source": "City of Toronto Open Data",
        "import": "yes",
        "bot": "no",
        "created_by": "t2-address-import",
        "import:client_token": token,
        "import_plan": "https://wiki.openstreetmap.org/wiki/Toronto/Import/AddressPoints",
    }


def _load_upload_items(run_id: int) -> list[dict]:
    """APPROVED candidates pending upload, with per-row data for tag building."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            """
            SELECT c.candidate_id, c.local_node_id, c.osm_node_id,
                   c.housenumber, c.street_raw, c.lat, c.lon,
                   cf.proposed_postcode
            FROM candidates c
            LEFT JOIN conflation cf ON cf.run_id = c.run_id AND cf.candidate_id = c.candidate_id
            WHERE c.run_id = ? AND c.stage = 'APPROVED'
            ORDER BY c.candidate_id
            """,
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def skip_cross_run_duplicates(run_id: int) -> list[int]:
    """First-come-first-served cross-run dedup.

    Adjacent batch tiles overlap, so one source address point can be APPROVED
    in several runs. Flip this run's APPROVED candidates to SKIPPED when the
    same source candidate_id is already UPLOADED in another run, so an address
    in an overlap band is imported exactly once. Idempotent; returns the
    candidate_ids skipped. Called before every upload path materializes the
    run's APPROVED set, so SKIPPED rows never enter the changeset and the
    API path's leftover-APPROVED partial-upload check stays accurate.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT c.candidate_id,
                   w.run_id      AS won_run,
                   w.osm_node_id AS won_osm
            FROM candidates c
            JOIN candidates w
              ON w.candidate_id = c.candidate_id
             AND w.run_id <> c.run_id
             AND w.stage = 'UPLOADED'
            WHERE c.run_id = ? AND c.stage = 'APPROVED'
            GROUP BY c.candidate_id
            """,
            (run_id,),
        ).fetchall()
        skipped: list[int] = []
        for r in rows:
            cid = int(r["candidate_id"])
            conn.execute(
                "UPDATE candidates SET stage='SKIPPED', stage_updated_at=? "
                "WHERE run_id=? AND candidate_id=?",
                (now, run_id, cid),
            )
            audit.log(
                actor="osm_export", event_type="SKIPPED_CROSS_RUN_DUPLICATE",
                run_id=run_id, candidate_id=cid,
                payload={"uploaded_in_run": r["won_run"],
                         "osm_node_id": r["won_osm"]},
                conn=conn,
            )
            skipped.append(cid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return skipped


def skip_intra_run_duplicates(run_id: int) -> list[int]:
    """Keep-one dedup within a single run's changeset.

    The conflate stage already auto-skips same-address Land siblings within
    5 m and flags wider pairs for review, but an operator can still APPROVE
    both flagged rows (or a >5 m pair), so the changeset would create two OSM
    nodes for one civic address. Group this run's APPROVED candidates by
    (address_full, municipality_name) — the same key conflate uses, which
    keeps the post-amalgamation "Municipality trap" (one address string in
    several former municipalities) as distinct addresses — and flip every row
    but the lowest candidate_id (the canonical keeper, matching conflate's
    tiebreak) to SKIPPED. Idempotent; returns the candidate_ids skipped.

    Scoped to one run_id (the candidates PK prefix), so it scans only that
    run's rows — no extra index needed. Called after skip_cross_run_
    duplicates on every upload path so the keeper is chosen among rows that
    will actually be uploaded, and SKIPPED rows never enter the changeset.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT c.candidate_id,
                   MIN(k.candidate_id) AS kept,
                   c.address_full      AS address_full,
                   c.municipality_name AS municipality_name
            FROM candidates c
            JOIN candidates k
              ON k.run_id = c.run_id
             AND k.stage = 'APPROVED'
             AND k.address_full = c.address_full
             AND k.municipality_name IS c.municipality_name
            WHERE c.run_id = ? AND c.stage = 'APPROVED'
              AND c.address_full IS NOT NULL
            GROUP BY c.candidate_id
            HAVING c.candidate_id <> MIN(k.candidate_id)
            ORDER BY c.candidate_id
            """,
            (run_id,),
        ).fetchall()
        skipped: list[int] = []
        for r in rows:
            cid = int(r["candidate_id"])
            conn.execute(
                "UPDATE candidates SET stage='SKIPPED', stage_updated_at=? "
                "WHERE run_id=? AND candidate_id=?",
                (now, run_id, cid),
            )
            audit.log(
                actor="osm_export", event_type="SKIPPED_INTRA_RUN_DUPLICATE",
                run_id=run_id, candidate_id=cid,
                payload={"kept_candidate_id": int(r["kept"]),
                         "address_full": r["address_full"],
                         "municipality_name": r["municipality_name"]},
                conn=conn,
            )
            skipped.append(cid)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return skipped


def _assign_local_node_ids(run_id: int, items: list[dict]) -> list[dict]:
    """Persist a stable negative local_node_id for each item that lacks one.
    Using -candidate_id keeps the id unique within the run and idempotent
    across re-exports — a JOSM download followed by an API upload of the same
    run still references the same node identities."""
    conn = _db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for it in items:
            if it.get("local_node_id") is None:
                lid = -int(it["candidate_id"])
                it["local_node_id"] = lid
                conn.execute(
                    "UPDATE candidates SET local_node_id=? WHERE run_id=? AND candidate_id=?",
                    (lid, run_id, it["candidate_id"]),
                )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return items


def build_tags(it: dict) -> dict[str, str]:
    """Tag dict for a candidate row. Emits a pure address node regardless of
    address_class — Structure Entrance rows are uploaded as plain addresses,
    not as entrance=yes nodes (see IMPORT_PROPOSAL_CHANGELOG.md 2026-05-06)."""
    tags = {
        "addr:housenumber": (it.get("housenumber") or "").strip(),
        "addr:street": (it.get("street_raw") or "").strip(),
        **STATIC_TAGS,
    }
    postcode = (it.get("proposed_postcode") or "").strip()
    if postcode:
        tags["addr:postcode"] = postcode
    return {k: v for k, v in tags.items() if v}


def _osm_change_xml(items: list[dict]) -> bytes:
    """Build an <osm version=0.6> element with one <node> per item."""
    root = ET.Element("osm", version="0.6", generator="t2-address-import")
    for it in items:
        lat, lon = it["lat"], it["lon"]
        if lat is None or lon is None:
            continue
        node = ET.SubElement(
            root, "node",
            id=str(it["local_node_id"]),
            lat=f"{lat:.7f}",
            lon=f"{lon:.7f}",
            action="modify",
            visible="true",
        )
        for k, v in build_tags(it).items():
            ET.SubElement(node, "tag", k=k, v=v)
    return ET.tostring(root, encoding="utf-8")


def write_xml(run_id: int) -> Path:
    skip_cross_run_duplicates(run_id)
    skip_intra_run_duplicates(run_id)
    items = _assign_local_node_ids(run_id, _load_upload_items(run_id))
    raw = _osm_change_xml(items)
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")

    # Embed the changeset-level tags as a header comment. JOSM does not
    # auto-apply these — the operator must paste them into the Upload dialog —
    # but having them in the file means the operator can recover them from a
    # text editor or JOSM's raw view if the run page isn't handy.
    cs_tags = changeset_tags(run_id)
    header_lines = ["<!-- Changeset tags (paste into JOSM upload dialog):"]
    for k, v in cs_tags.items():
        header_lines.append(f"     {k} = {v}")
    header_lines.append("-->")
    header = ("\n".join(header_lines) + "\n").encode("utf-8")

    decl, _, body = pretty.partition(b"\n")
    out = _CONFIG.data_dir / f"upload_run_{run_id}.osm"
    out.write_bytes(decl + b"\n" + header + body)
    return out


def osmchange_xml(run_id: int, changeset_id: int) -> bytes:
    """Build an osmChange 0.6 document for direct API upload."""
    items = _assign_local_node_ids(run_id, _load_upload_items(run_id))
    root = ET.Element("osmChange", version="0.6", generator="t2-address-import")
    create = ET.SubElement(root, "create")
    for it in items:
        lat, lon = it["lat"], it["lon"]
        if lat is None or lon is None:
            continue
        node = ET.SubElement(
            create, "node",
            id=str(it["local_node_id"]),
            changeset=str(changeset_id),
            lat=f"{lat:.7f}",
            lon=f"{lon:.7f}",
            version="0",
        )
        for k, v in build_tags(it).items():
            ET.SubElement(node, "tag", k=k, v=v)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def items_for_view(run_id: int) -> list[dict]:
    """Items table on the run page: APPROVED + UPLOADED candidates with their
    local/osm node ids so the operator can see what's queued and what's gone."""
    conn = _db.connect()
    try:
        rows = conn.execute(
            """
            SELECT c.candidate_id, c.local_node_id, c.osm_node_id, c.stage,
                   c.housenumber, c.street_raw, c.lat, c.lon
            FROM candidates c
            WHERE c.run_id = ? AND c.stage IN ('APPROVED','UPLOADED')
            ORDER BY c.stage, c.candidate_id
            """,
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
