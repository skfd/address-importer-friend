"""Operator verdicts on the collapse-vs-nodes decision, from chip to emitter.

Three layers, tested separately because they fail separately: `units.resolve`
turns (rule, override) into a shape and must agree with itself whichever
caller asks; `_emit_group` turns that shape into rows and has one deliberate
relabelling; `unit_verdicts` persists the decision and refuses it once the
group is in OSM.
"""
import pytest

from t2 import db as _db, source_db, unit_verdicts, units
from t2.candidates import _elect, _emit_group, _iter_emissions
from t2.unit_shapes import _outcome

_M = 1.0 / 111320.0


def _src(pid, unit=None, index=0, spacing_m=6.0, lat=43.54, lon=-80.25):
    return {
        "address_point_id": pid,
        "unit_name": unit,
        "latitude": lat + index * spacing_m * _M,
        "longitude": lon,
        "address_number": "7",
        "linear_name_full": "Test Street",
        "municipality_name": "Guelph",
    }


def _tower():
    return [_src(f"u{f}{n}", f"{f}{n:02d}") for f in range(1, 5) for n in range(1, 4)]


def _doors():
    return [_src(f"d{i}", str(40 + i), index=i) for i in range(1, 13)]


def _over_long():
    # 85 Mullin Drive: 1A;1B;2A;2B... to 421 characters. Nothing compresses it.
    return [_src(f"s{n}{s}", f"{n}{s}", index=0) for n in range(1, 56) for s in ("A", "B")]


def _all(_row):
    return True


def _emit(group, override=None):
    return [(r["address_point_id"], u, f, shape, why) for r, u, f, shape, why in _emit_group(group, _all, override)]


# --- the emitter honours each verdict -----------------------------------------


def test_nodes_override_explodes_a_tower_and_keeps_the_rules_opinion():
    out = _emit(_tower(), "nodes")
    assert len(out) == 12
    assert {shape for *_, shape, _why in out} == {"nodes"}
    assert all(u is not None and f is None for _pid, u, f, _s, _w in out)
    assert out[0][4].startswith("override: rule said collapse")


def test_collapse_override_folds_a_row_of_doors_into_one_listing():
    out = _emit(_doors(), "collapse")
    assert len(out) == 1
    pid, unit, flats, shape, why = out[0]
    assert pid == _elect(_doors())["address_point_id"]
    assert (unit, flats, shape) == (None, "41-52", "collapse")
    assert why.startswith("override: rule said nodes")


def test_collapse_override_cannot_make_a_long_listing_fit():
    """The override changes the branch, never the 255-character limit. The
    group falls through to civic-only, and because nobody chose civic-only
    the candidate is still labelled review so a human is told."""
    out = _emit(_over_long(), "collapse")
    assert len(out) == 1
    _pid, unit, flats, shape, why = out[0]
    assert flats is None
    assert shape == "review"
    assert why.startswith("override to collapse cannot fit")
    assert "255" in why


def test_civic_only_override_is_a_choice_not_a_failure():
    out = _emit(_over_long(), "civic-only")
    assert len(out) == 1
    _pid, unit, flats, shape, why = out[0]
    assert (unit, flats, shape) == (None, None, "civic-only")
    assert why.startswith("override: rule said")


def test_skip_override_creates_nothing():
    assert _emit(_tower(), "skip") == []
    assert _emit(_doors(), "skip") == []


def test_a_dropped_listing_nobody_chose_is_still_labelled_review():
    out = _emit(_over_long())
    assert len(out) == 1
    assert out[0][3] == "review"
    assert "255" in out[0][4]


def test_an_unknown_override_is_refused_loudly():
    with pytest.raises(ValueError):
        units.resolve(units.COLLAPSE, "r", ["101"], "explode")


# --- the page and the emitter agree, override or not ---------------------------


@pytest.mark.parametrize("override", [None, "nodes", "collapse", "civic-only", "skip"])
@pytest.mark.parametrize("group", [_tower(), _doors(), _over_long()])
def test_the_page_describes_what_the_emitter_does(group, override):
    page = _outcome(group, override)
    emitted = list(_emit_group(group, _all, override))
    assert page["nodes_created"] == len(emitted)
    flats = {f for _r, _u, f, _s, _w in emitted}
    assert flats == ({page["flats"]} if emitted else set())
    if page["shape"] == "nodes":
        assert all(s == "nodes" for _r, _u, _f, s, _w in emitted)


# --- the hash is over designators only -----------------------------------------


def test_unit_hash_ignores_where_the_units_are_and_how_they_are_ordered():
    a = units.unit_hash(units.listed_units(["101", "102", "201"]))
    b = units.unit_hash(units.listed_units([" 201", "101 ", "102", "102"]))
    assert a == b


def test_unit_hash_changes_when_the_building_gains_a_floor():
    a = units.unit_hash(units.listed_units(["101", "102"]))
    b = units.unit_hash(units.listed_units(["101", "102", "201"]))
    assert a != b


def test_the_emitter_and_the_page_hash_the_same_group_the_same_way():
    """`_iter_emissions` looks a verdict up by the hash it computes from the
    group; the page saved it under the hash it computed. One helper, both
    sides, or a verdict is never recognised."""
    group = _tower()
    listed = units.listed_units(r["unit_name"] for r in group)
    assert _outcome(group)["units"] == listed
    assert units.unit_hash(listed) == units.unit_hash(_outcome(group)["units"])


# --- persistence, staleness, freeze --------------------------------------------


@pytest.fixture
def tool_db(tmp_path, monkeypatch):
    monkeypatch.setattr(_db._CONFIG, "tool_db_path", tmp_path / "tool.db")
    monkeypatch.setattr(_db._CONFIG, "data_dir", tmp_path)
    _db.migrate()
    return tmp_path


KEY = source_db.civic_key_text(("7", "Test Street", "Guelph"))


def test_civic_key_text_is_case_and_space_insensitive_and_survives_a_missing_part():
    assert KEY == "7|TEST STREET|GUELPH"
    assert source_db.civic_key_text((" 7 ", "test street", None)) == "7|TEST STREET|"


def test_a_saved_verdict_is_read_back_and_a_repeat_is_a_no_op(tool_db):
    assert unit_verdicts.save(KEY, "skip", "abc", "a mall") is True
    assert unit_verdicts.save(KEY, "skip", "abc", "a mall") is False
    saved = unit_verdicts.load_all()[KEY]
    assert (saved["verdict"], saved["unit_hash"], saved["note"]) == ("skip", "abc", "a mall")
    assert unit_verdicts.effective(saved, "abc") == "skip"


def test_a_verdict_about_a_different_unit_set_is_stale_and_does_not_apply(tool_db):
    unit_verdicts.save(KEY, "nodes", "old-hash")
    saved = unit_verdicts.load_all()[KEY]
    assert unit_verdicts.effective(saved, "new-hash") is None


def test_clearing_a_verdict_hands_the_group_back_to_the_rule(tool_db):
    unit_verdicts.save(KEY, "nodes", "h")
    assert unit_verdicts.clear(KEY) is True
    assert KEY not in unit_verdicts.load_all()
    assert unit_verdicts.clear(KEY) is False


def test_version_moves_when_a_verdict_does(tool_db):
    before = unit_verdicts.version()
    unit_verdicts.save(KEY, "collapse", "h")
    assert unit_verdicts.version() != before


def _candidate(conn, run_id, cid, stage, civic_key):
    conn.execute(
        "INSERT INTO runs (run_id, name, bbox_min_lat, bbox_min_lon, bbox_max_lat, "
        "bbox_max_lon, created_at, config_json) VALUES (?, ?, 0, 0, 1, 1, 't', '{}') "
        "ON CONFLICT DO NOTHING",
        (run_id, f"run-{run_id}"),
    )
    conn.execute(
        "INSERT INTO candidates (run_id, candidate_id, address_full, stage, "
        "stage_updated_at, civic_key) VALUES (?, ?, ?, ?, 't', ?)",
        (run_id, cid, f"{cid} Test St", stage, civic_key),
    )


def test_an_uploaded_door_freezes_its_whole_group(tool_db):
    with _db.tx() as conn:
        _candidate(conn, 1, 100, "UPLOADED", KEY)
        _candidate(conn, 1, 101, "APPROVED", KEY)
    assert unit_verdicts.frozen_keys() == {KEY}
    with pytest.raises(unit_verdicts.Frozen):
        unit_verdicts.save(KEY, "collapse", "h")
    with pytest.raises(unit_verdicts.Frozen):
        unit_verdicts.clear(KEY)
    assert KEY not in unit_verdicts.load_all()


def test_a_rejected_candidate_in_an_uploaded_run_does_not_freeze(tool_db):
    """Freeze means "reached OSM", which is the candidate's stage, not the
    run's upload flag: a REJECTED row never left the database."""
    with _db.tx() as conn:
        _candidate(conn, 1, 100, "REJECTED", KEY)
        conn.execute("UPDATE runs SET upload_status='uploaded' WHERE run_id=1")
    assert unit_verdicts.frozen_keys() == set()
    assert unit_verdicts.save(KEY, "skip", "h") is True


def test_the_freeze_stamp_outlives_the_upload_row(tool_db):
    unit_verdicts.save(KEY, "nodes", "h")
    with _db.tx() as conn:
        _candidate(conn, 1, 100, "UPLOADED", KEY)
    with pytest.raises(unit_verdicts.Frozen):
        unit_verdicts.save(KEY, "collapse", "h")
    assert unit_verdicts.load_all()[KEY]["frozen_at"]
    with _db.tx() as conn:
        conn.execute("DELETE FROM candidates")
    with pytest.raises(unit_verdicts.Frozen):
        unit_verdicts.save(KEY, "collapse", "h")


def test_ingested_runs_names_where_a_group_already_landed(tool_db):
    with _db.tx() as conn:
        _candidate(conn, 3, 100, "INGESTED", KEY)
        _candidate(conn, 5, 101, "APPROVED", KEY)
        _candidate(conn, 5, 102, "APPROVED", "9|OTHER|GUELPH")
    assert unit_verdicts.ingested_runs()[KEY] == [3, 5]
    assert unit_verdicts.ingested_runs({KEY}) == {KEY: [3, 5]}


# --- end to end: a verdict reaches ingest, a stale one does not ----------------


def _emissions(monkeypatch, group, verdict_row):
    monkeypatch.setattr(source_db, "PER_DOOR", True)
    monkeypatch.setattr(source_db, "iter_active_addresses_in_bbox", lambda bbox, snap: iter(group))
    monkeypatch.setattr(
        source_db, "fetch_civic_groups", lambda keys, snap: {source_db.civic_key(group[0]): group}
    )
    monkeypatch.setattr(unit_verdicts, "load_all", lambda: {KEY: verdict_row} if verdict_row else {})
    return list(_iter_emissions((0, 0, 90, 0), 1, None, None, _all))


def test_a_matching_verdict_is_honoured_at_ingest_and_the_key_travels(monkeypatch):
    group = _tower()
    h = units.unit_hash(units.listed_units(r["unit_name"] for r in group))
    out = _emissions(monkeypatch, group, {"verdict": "nodes", "unit_hash": h})
    assert len(out) == 12
    assert {e[3] for e in out} == {"nodes"}
    assert {e[5] for e in out} == {KEY}


def test_a_stale_verdict_is_ignored_at_ingest(monkeypatch):
    out = _emissions(monkeypatch, _tower(), {"verdict": "nodes", "unit_hash": "from-before-the-new-floor"})
    assert len(out) == 1
    assert out[0][3] == "collapse"


def test_without_a_verdict_the_rule_decides_and_the_key_still_travels(monkeypatch):
    out = _emissions(monkeypatch, _doors(), None)
    assert len(out) == 12
    assert {e[5] for e in out} == {KEY}
