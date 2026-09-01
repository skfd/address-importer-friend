"""Emit JOSM-compatible .osm XML and osmChange XML for a run's APPROVED candidates."""
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from xml.dom import minidom

from . import audit, config as _config, db as _db

_CONFIG = _config.load()

def _attribution() -> str:
    """`addr:source` tag for every node we create, and `source` on the
    changeset. Deliberately checked here rather than at config load: a city can
    conflate and be reviewed before its attribution string is settled, but it
    must never upload without one."""
    value = _CONFIG.export_attribution
    if not value:
        raise ValueError(
            "config.toml [export] attribution is empty — it becomes the "
            "`addr:source` tag on every uploaded node and cannot be omitted."
        )
    return value


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


def changeset_comment(run_name: str) -> str:
    """The changeset `comment` tag, rendered from the city's template.

    One owner for the substitution. The template gained `{city}` when the tool
    went multi-city, and the two places that rendered it drifted: this one
    passed both keys, the upload path in `osm_client` still passed only
    `run_name` and died with `KeyError: 'city'` the moment a city actually used
    the placeholder — mid-upload, after the run was reviewed and approved."""
    return _CONFIG.changeset_comment_template.format(
        run_name=run_name, city=_CONFIG.city_name
    )


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
    comment = changeset_comment(row["name"])
    if not _CONFIG.export_import_plan:
        raise ValueError(
            "config.toml [export] import_plan is empty — the changeset must point "
            "at this city's import wiki page."
        )
    tags = {
        "comment": comment,
        "source": _attribution(),
        "import": "yes",
        "bot": "no",
        "created_by": "address-importer-friend",
        "import:client_token": token,
        "import_plan": _CONFIG.export_import_plan,
    }
    # Optional, and absent for Toronto: its published changeset-tag table names
    # no licence. Guelph's names OGL-Canada-2.0.
    if _CONFIG.export_source_license:
        tags["source:license"] = _CONFIG.export_source_license
    return tags


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


#: Separators that start a new capitalized part inside one whitespace-free
#: word: "Saint-Louis", "Cnr/Wallbridge".
_WORD_PARTS = re.compile(r"([-/])")


def _cap_word(word: str) -> str:
    """Capitalize one space- and hyphen-free word, apostrophes included.

    A segment after an apostrophe is capitalized only when it is more than one
    character: "O'NEIL" is "O'Neil" but "GOVERNOR'S" is "Governor's", not
    "Governor'S".
    """
    segs = word.split("'")
    out = [segs[0][:1].upper() + segs[0][1:].lower()]
    for seg in segs[1:]:
        out.append(seg[:1].upper() + seg[1:].lower() if len(seg) > 1 else seg.lower())
    return "'".join(out)


def _cap_mc(word: str) -> str:
    """Restore the "Mc" convention inside an already-capitalized word.

    "Mccraney" -> "McCraney", "Mcgill" -> "McGill". Only fires on a word this
    module just capitalized from an all-caps source, where the surname's own
    case was destroyed by the publisher and has to be invented; `accordeur`
    deliberately never re-cases a name that arrived with case, which is why
    "Mcgee Street" written that way in a mixed-case source stays "Mcgee".

    "Mac" is left alone, the same call `accordeur.glue_mc` makes — and OSM
    Toronto's own addr:street values say why. "Mc" is all but unanimous there:
    68 distinct names capitalize the third letter (1,389 values), 4 do not, and
    those 4 read as typos ("Mccowan"). "Mac" is genuinely split: 16 distinct
    capitalize (MacGregor, MacPherson) and 20 do not — and that second list is
    not sloppiness, it holds words where a capital would be wrong (Macaulay,
    Macedonia, Macey, Mackinac, Macklem, Machockie). Six surnames appear both
    ways on different streets. No rule can separate them, so "MACDONALD"
    becomes "Macdonald" and a city that wants "MacDonald" writes it in
    `[streets] overrides`.
    """
    if len(word) > 3 and word.startswith("Mc") and word[2:].isalpha():
        return "Mc" + word[2].upper() + word[3:]
    return word


def title_case_street(name: str) -> str:
    """Rewrite an ALL-CAPS street name in OSM's mixed case ("ANNA COURT" ->
    "Anna Court"). Export path only — see `config.parse_street_case`.

    **A word that already carries any lowercase letter is returned untouched.**
    That is what makes the step idempotent and safe to run after
    `expand_street_name`, which has already produced OSM's spelling for the
    trailing tokens: "MCCRANEY Street" title-cases to "McCraney Street" without
    the risk of a second pass flattening "McCraney" to "Mccraney". It also means
    a `[streets] overrides` value, which is written in OSM's own spelling,
    passes through as the operator wrote it.

    Hyphens and slashes split a word before it is capitalized ("SAINT-LOUIS" ->
    "Saint-Louis", Quinte West's "CNR/WALLBRIDGE-LOYALIST ROAD" ->
    "Cnr/Wallbridge-Loyalist Road"); digits are left as they are, so "COUNTY
    ROAD 40" becomes "County Road 40" and "3RD LINE" becomes "3rd Line".

    An acronym cannot be recovered: an ALL-CAPS source spells "YMCA" exactly
    the way it spells "MAIN", so "YMCA BOULEVARD" becomes "Ymca Boulevard".
    That is what `[streets] overrides` is for.

    **Every word is capitalized, including "of", "the" and "de".** An earlier
    draft lowercased medial particles the way English prose titles do; measured
    against OSM Toronto's 13,170 distinct addr:street values it was a coin
    flip, and it got the proper nouns wrong in both cases that matter: OSM
    writes "Chester Le Boulevard" (53) and "Vittorio De Luca Drive" (18), where
    the particle is part of a name, against "Avenue of the Islands" (30) and
    "Avenue Of The Islands" (10) for the same street. No casing rule separates
    a surname's "De" from a preposition's "of", so the step does not try: a
    city that wants one writes it in `[streets] overrides`, which is the
    mechanism for "the source and OSM disagree about the actual name".
    """
    if not name:
        return name
    out: list[str] = []
    for word in name.split():
        if any(ch.islower() for ch in word):
            out.append(word)
        else:
            out.append("".join(
                part if part in "-/" else _cap_mc(_cap_word(part))
                for part in _WORD_PARTS.split(word)))
    return " ".join(out)


def build_tags(it: dict) -> dict[str, str]:
    """Tag dict for a candidate row — the one owner, for preview and upload
    alike. `conflate._proposed_tags` calls this and adds only its POI-postcode
    fallback on top, so the review UI cannot drift from the changeset again.

    Emits a pure address node regardless of address_class — Structure Entrance
    rows are uploaded as plain addresses, not as entrance=yes nodes (see
    IMPORT_PROPOSAL_CHANGELOG.md 2026-05-06).

    `addr:source` rather than a bare `source`: it sources the *address*, sits
    in the addr:* namespace with the tags it belongs to, and survives a later
    merge into a building polygon without claiming to source the building. The
    changeset keeps the plain `source` key — that one is about the edit.

    `[export] node_tags` appends the city's constant tags (Guelph's published
    plan promises addr:city=Guelph; Toronto declares none and writes none).
    Config cannot redefine a derived tag — parse_node_tags refuses that at
    load — so the splat is safe last.

    `[export] street_case = "title"` title-cases addr:street here and nowhere
    else. The stored `street_raw` keeps the source's own spelling, so the flag
    can be added or corrected without re-ingesting a city, and conflation --
    which compares through `normalize_street` -- cannot move either way.

    Reads `export_attribution` raw rather than through `_attribution()`: an
    unset attribution drops the tag here (the empty-value filter below) and
    stops the *upload* instead, in `changeset_tags`, which every upload path
    goes through. A city being scaffolded must still be able to conflate and
    open the review UI before its attribution string is settled.
    """
    street = (it.get("street_raw") or "").strip()
    if _CONFIG.export_street_case == "title":
        street = title_case_street(street)
    tags = {
        "addr:housenumber": (it.get("housenumber") or "").strip(),
        "addr:street": street,
        "addr:source": _CONFIG.export_attribution,
    }
    postcode = (it.get("proposed_postcode") or "").strip()
    if postcode:
        tags["addr:postcode"] = postcode
    tags.update(_CONFIG.export_node_tags)
    return {k: v for k, v in tags.items() if v}


def _osm_change_xml(items: list[dict], cs_tags: dict[str, str] | None = None) -> bytes:
    """Build an <osm version=0.6> element with one <node> per item.

    `cs_tags` becomes a `<changeset>` child, which JOSM reads into the layer
    and uses to pre-fill the Upload dialog — see `write_xml`.
    """
    root = ET.Element("osm", version="0.6", generator="t2-address-import")
    if cs_tags:
        # No `id` attribute: JOSM accepts the element only when its id equals
        # the root's `upload-changeset` attribute, and null == null is the
        # match a hand-built file wants. An id here would make JOSM skip the
        # whole element without a word.
        cs = ET.SubElement(root, "changeset")
        for k, v in cs_tags.items():
            ET.SubElement(cs, "tag", k=k, v=v)
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
    # The changeset tags ride in a real `<changeset>` element, not a comment.
    # JOSM's OsmReader parses it into the layer (AbstractReader.prepareDataSet
    # -> ds.addChangeSetTag) and UploadDialog.initLifeCycle copies those over
    # the history-based prefill, so opening this file fills in the comment,
    # source and the rest by itself. Only the `.osm` reader does this —
    # OsmChangeReader ignores anything that is not create/modify/delete, so the
    # same tags in an `.osc` would go nowhere.
    raw = _osm_change_xml(items, changeset_tags(run_id))
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
    out = _CONFIG.data_dir / f"upload_run_{run_id}.osm"
    out.write_bytes(pretty)
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
