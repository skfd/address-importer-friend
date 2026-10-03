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


# --- the page sees a freeze that happened after it was first drawn --------------


def _synthetic_base(monkeypatch):
    from t2 import unit_shapes

    group = _tower()
    listed = units.listed_units(r["unit_name"] for r in group)
    row = {
        "key": KEY, "dom": "abc", "number": "7", "street": "Test Street",
        "municipality": "Guelph", "unit_count": len(listed), "row_count": len(group),
        "lat": 43.54, "lon": -80.25, "verdict": units.COLLAPSE, "rule_reason": "floor-coded",
        "units": listed, "unit_hash": units.unit_hash(listed),
    }
    monkeypatch.setattr(unit_shapes, "_base", lambda snap: {"snapshot_id": snap, "rows": [row], "no_unit_groups": 0})
    monkeypatch.setattr(source_db, "latest_snapshot_id", lambda conn=None: 1)
    return unit_shapes


def test_the_page_reflects_an_upload_made_after_it_was_drawn(tool_db, monkeypatch):
    """`collect()` must not cache the overlay: freeze comes from the candidates
    table, which moves on every upload without any verdict changing."""
    unit_shapes = _synthetic_base(monkeypatch)
    first = unit_shapes.collect()["by_key"][KEY]
    assert first["frozen"] is False and first["ingested_runs"] == []
    unit_shapes.decide(KEY, "nodes", "walkup")
    assert unit_shapes.collect()["by_key"][KEY]["override"] == "nodes"
    with _db.tx() as conn:
        _candidate(conn, 4, 100, "UPLOADED", KEY)
    again = unit_shapes.collect()["by_key"][KEY]
    assert again["frozen"] is True
    assert again["ingested_runs"] == [4]
    with pytest.raises(unit_verdicts.Frozen):
        unit_shapes.decide(KEY, "collapse")
    assert unit_shapes.collect()["by_key"][KEY]["shape"] == "nodes"


def test_decide_hashes_the_group_as_the_page_sees_it(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    row = unit_shapes.decide(KEY, "skip")
    assert row["shape"] == "skip" and row["nodes_created"] == 0
    assert unit_verdicts.load_all()[KEY]["unit_hash"] == row["unit_hash"]
    row = unit_shapes.decide(KEY, "rule")
    assert row["override"] is None and row["shape"] == "collapse"


# --- what OSM already holds: the second freeze condition ----------------------


def _el(kind, id_, tags, lat=43.54, lon=-80.25, nodes=None):
    el = {"type": kind, "id": id_, "tags": tags}
    if kind == "node":
        el.update(lat=lat, lon=lon)
    else:
        el["center"] = {"lat": lat, "lon": lon}
    if nodes:
        el["nodes"] = nodes
    return el


def test_osm_summary_reads_both_encodings_of_a_door():
    from t2.unit_shapes import _osm_summaries

    idx = _osm_summaries([
        _el("node", 1, {"addr:housenumber": "714", "addr:street": "Test Street"}),
        _el("node", 2, {"addr:housenumber": "714", "addr:street": "Test Street", "addr:unit": "30"}),
        _el("node", 3, {"addr:housenumber": "714-31", "addr:street": "Test Street", "addr:unit": "31"}),
        _el("way", 4, {"addr:housenumber": "714-32", "addr:street": "Test Street"}),
        # A shop at the address is acknowledged, not an address object.
        _el("node", 5, {"addr:housenumber": "714", "addr:street": "Test Street", "shop": "bakery"}),
    ])
    s = idx[("TEST ST", "714")]
    assert s["civic"] == 1
    assert s["units"] == {"30"}
    assert s["hyphenated"] == {"31", "32"}
    assert ("node", 5) not in s["ids"]


def test_osm_summary_drops_interpolation_endpoints_and_keeps_listings():
    from t2.unit_shapes import _osm_summaries

    idx = _osm_summaries([
        _el("way", 9, {"addr:interpolation": "even"}, nodes=[7]),
        _el("node", 7, {"addr:housenumber": "2", "addr:street": "Test Street"}),
        _el("node", 8, {"addr:housenumber": "4", "addr:street": "Test Street", "addr:flats": "1-6"}),
    ])
    assert ("TEST ST", "2") not in idx
    assert idx[("TEST ST", "4")]["listings"] == ["1-6"]


def test_a_building_listing_its_units_under_addr_unit_is_a_listing_not_a_door():
    """Guelph's towers: one way, addr:unit=101-116;201-215;... That is the
    collapsed shape already in OSM, not one unit object."""
    from t2.unit_shapes import _osm_summaries

    idx = _osm_summaries([
        _el("way", 1, {"addr:housenumber": "1878", "addr:street": "Gordon Street", "building": "apartments",
                       "addr:unit": "101-116;201-215;301-314"}),
        _el("way", 2, {"addr:housenumber": "1880", "addr:street": "Gordon Street", "addr:unit": "1-10"}),
        _el("node", 3, {"addr:housenumber": "1882", "addr:street": "Gordon Street", "addr:unit": "PH-2"}),
    ])
    assert idx[("GORDON ST", "1878")]["listings"] == ["101-116;201-215;301-314"]
    assert idx[("GORDON ST", "1878")]["units"] == set()
    assert idx[("GORDON ST", "1880")]["listings"] == ["1-10"]
    assert idx[("GORDON ST", "1882")]["units"] == {"PH-2"}


def test_a_group_somebody_else_mapped_as_doors_still_takes_a_verdict(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    doors = {("TEST ST", "7"): {"civic": 1, "units": {"1", "2"}, "hyphenated": {"3"}, "listings": [], "ids": [("node", 1)]}}
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: doors)
    row = unit_shapes.collect()["by_key"][KEY]
    assert row["osm"]["shape"] == "doors" and row["osm"]["doors"] == 3 and row["osm"]["hyphenated"] == 1
    assert not row["frozen"] and "3 of" in row["in_osm"]
    # 15 Carere Crescent: two doors in OSM must not lock the other 64 out.
    assert unit_shapes.decide(KEY, "nodes")["override"] == "nodes"
    assert unit_shapes.select(unit_shapes.collect()["rows"], osm="open") == []


def test_a_bare_civic_node_in_osm_does_not_freeze(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    civic = {("TEST ST", "7"): {"civic": 1, "units": set(), "hyphenated": set(), "listings": [], "ids": []}}
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: civic)
    row = unit_shapes.collect()["by_key"][KEY]
    assert row["osm"]["shape"] == "civic" and not row["frozen"]
    assert unit_shapes.decide(KEY, "nodes")["override"] == "nodes"


def test_a_building_already_listing_its_units_still_takes_a_verdict(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    listing = {("TEST ST", "7"): {"civic": 0, "units": set(), "hyphenated": set(), "listings": ["101-112"],
                                  "ids": [("way", 1)], "listing_ids": [("way", 1, "101-112")]}}
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: listing)
    row = unit_shapes.collect()["by_key"][KEY]
    assert row["osm"]["shape"] == "listing" and not row["frozen"]
    assert "lists the units" in row["in_osm"]
    assert row["osm"]["listing_ids"] == [("way", 1, "101-112")]
    assert unit_shapes.decide(KEY, "nodes")["override"] == "nodes"


def test_an_auto_judged_verdict_is_labelled_auto(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: {})
    assert unit_shapes.decide(KEY, "nodes", "auto: 66 units in 34 buildings")["auto"] is True
    assert unit_shapes.decide(KEY, "nodes", "townhouses, checked")["auto"] is False
    rows = unit_shapes.collect()["rows"]
    assert [r["key"] for r in unit_shapes.select(rows, osm="decided")] == [KEY]


def test_osm_summary_keeps_every_listing_object_with_its_listing():
    """The review map outlines each one; `ids` is only a sample of three."""
    from t2.unit_shapes import _osm_summaries

    idx = _osm_summaries([
        _el("way", 10 + i, {"addr:housenumber": "941", "addr:street": "Gordon Street", "addr:flats": f"{i}1-{i}4"})
        for i in range(1, 6)
    ] + [
        _el("way", 20, {"addr:housenumber": "941", "addr:street": "Gordon Street", "addr:unit": "1-4"}),
        _el("node", 21, {"addr:housenumber": "941", "addr:street": "Gordon Street", "addr:unit": "7"}),
    ])
    s = idx[("GORDON ST", "941")]
    assert [(t, i) for t, i, _v in s["listing_ids"]] == [("way", 11), ("way", 12), ("way", 13), ("way", 14), ("way", 15), ("way", 20)]
    assert s["listing_ids"][0][2] == "11-14" and s["listing_ids"][-1][2] == "1-4"


def test_without_an_extract_the_column_is_absent_not_empty(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: None)
    data = unit_shapes.collect()
    assert data["osm_loaded"] is False
    assert data["by_key"][KEY]["osm"] is None and not data["by_key"][KEY]["frozen"]


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


# --- the page: listing filter and review queue render --------------------------


def _client(monkeypatch):
    from t2.web.app import create_app

    monkeypatch.setattr(source_db, "PER_DOOR", True)
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_the_review_queue_draws_a_card_with_its_points_and_listing_refs(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    listing = {("TEST ST", "7"): {"civic": 0, "units": set(), "hyphenated": set(), "listings": ["101-112"],
                                  "ids": [("way", 1)], "listing_ids": [("way", 1, "101-112")]}}
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: listing)
    unit_shapes._base(1)["rows"][0]["points"] = [("101", 43.54, -80.25)]
    client = _client(monkeypatch)

    page = client.get("/units/shapes?osm=listing&mode=queue").get_data(as_text=True)
    assert 'class="q-card' in page
    assert '[[&#34;way&#34;, 1, &#34;101-112&#34;]]' in page or '[["way", 1, "101-112"]]' in page
    # A listed group takes a verdict, and the card says what OSM already has.
    assert 'name="mode" value="queue"' in page and "In OSM already" in page

    # A verdict in the queue swaps only the chips, not the card with the map.
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: {})
    page = client.get("/units/shapes?mode=queue").get_data(as_text=True)
    assert 'name="mode" value="queue"' in page
    out = client.post("/units/shapes/verdict", data={
        "civic_key": KEY, "choice": "nodes", "mode": "queue"}).get_data(as_text=True)
    assert out.lstrip().startswith('<div class="q-decide">')
    assert 'q-card' not in out and '<template>' not in out
    assert unit_verdicts.load_all()[KEY]["verdict"] == "nodes"


def test_the_listing_filter_hides_groups_osm_does_not_list(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: {})
    client = _client(monkeypatch)
    assert "No civic groups in this shape." in client.get("/units/shapes?osm=listing").get_data(as_text=True)
    assert "7 Test Street" in client.get("/units/shapes").get_data(as_text=True)


# --- split: a tower with a row of townhouses on the same civic number -----------


def _tower_with_rows():
    # 53 Arthur Street South in miniature: floor-coded suites in one spot, a
    # lettered row of doors 5.5 m apart, and a lower level that is a floor.
    tower = [_src(f"u{f}{n}", f"{f}{n:02d}", spacing_m=0.5, index=n) for f in range(1, 5) for n in range(1, 4)]
    row = [_src(f"rl{i}", f"RL{i}", index=i, spacing_m=5.5, lon=-80.251) for i in range(1, 5)]
    lower = [_src(f"ll{i}", f"LL0{i}", index=i, spacing_m=0.5) for i in range(1, 3)]
    return tower + row + lower


def test_split_doors_takes_the_sequential_lettered_row_and_leaves_the_floors():
    rows = [{"unit": r["unit_name"], "lat": r["latitude"], "lon": r["longitude"]} for r in _tower_with_rows()]
    assert units.split_doors(rows) == {"RL1", "RL2", "RL3", "RL4"}


def test_split_emits_the_row_as_doors_and_lists_only_the_suites():
    out = _emit(_tower_with_rows(), "split")
    doors = [(u, s) for _pid, u, _f, s, _w in out if u]
    building = [(f, s) for _pid, u, f, s, _w in out if u is None]
    assert sorted(doors) == [("RL1", "nodes"), ("RL2", "nodes"), ("RL3", "nodes"), ("RL4", "nodes")]
    assert len(building) == 1 and building[0][1] == "collapse"
    assert "RL" not in building[0][0] and "LL01;LL02" in building[0][0] and "101-103" in building[0][0]
    page = _outcome(_tower_with_rows(), "split")
    assert page["shape"] == "split" and page["nodes_created"] == len(out) == 5
    assert page["flats"] == building[0][0]


def test_split_with_no_door_row_falls_back_to_collapse_and_says_so():
    shape, reason, flats = units.resolve(units.COLLAPSE, "floor-coded", ["101", "201"], "split", set())
    assert shape == "collapse" and "found no door row" in reason and flats


def test_a_split_verdict_saves_and_shows_its_doors(tool_db, monkeypatch):
    unit_shapes = _synthetic_base(monkeypatch)
    monkeypatch.setattr(unit_shapes, "_osm_index", lambda: {})
    group = _tower_with_rows()
    base = unit_shapes._base(1)["rows"][0]
    listed = units.listed_units(r["unit_name"] for r in group)
    base.update(units=listed, unit_hash=units.unit_hash(listed), row_count=len(group),
                points=[(r["unit_name"], r["latitude"], r["longitude"]) for r in group])
    row = unit_shapes.decide(KEY, "split")
    assert row["shape"] == "split" and row["split_doors"] == ["RL1", "RL2", "RL3", "RL4"]
    assert row["nodes_created"] == 5
