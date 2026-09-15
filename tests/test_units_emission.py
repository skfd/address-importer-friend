"""What a civic group becomes at ingest under per-door-or-collapse.

`_emit_group` is where the classifier's verdict turns into rows, and where
tile clipping happens. The tile part is the subtle half: the group handed in is
always the whole civic group city-wide, so every tile sees the same units and
has to agree on which of them are *its*.
"""
from t2.candidates import _elect, _emit_group

_M = 1.0 / 111320.0


def _src(pid, unit=None, index=0, spacing_m=6.0, lat=43.54, lon=-80.25):
    return {
        "address_point_id": pid,
        "unit_name": unit,
        "latitude": lat + index * spacing_m * _M,
        "longitude": lon,
    }


def _all(_row):
    return True


def _none(_row):
    return False


def _emit(group, in_tile=_all):
    return [(r["address_point_id"], u, f) for r, u, f in _emit_group(group, in_tile)]


# --- election ---------------------------------------------------------------


def test_the_unit_less_row_is_elected_over_any_unit():
    group = [_src("b", "101"), _src("a", "201"), _src("z", None)]
    assert _elect(group)["address_point_id"] == "z"


def test_without_a_unit_less_row_the_lowest_id_wins():
    group = [_src("b", "101"), _src("a", "201")]
    assert _elect(group)["address_point_id"] == "a"


# --- doors ------------------------------------------------------------------


def test_a_townhouse_row_emits_one_node_per_door():
    group = [_src(f"d{i}", str(40 + i), index=i) for i in range(1, 13)]
    out = _emit(group)
    assert len(out) == 12
    assert all(flats is None for _pid, _u, flats in out)
    assert {u for _pid, u, _f in out} == {str(n) for n in range(41, 53)}


def test_the_civic_row_survives_alongside_its_doors():
    """The City publishes it as its own point, and under unit-aware matching it
    is a different object from any door rather than a duplicate of one."""
    group = [_src("civic", None, index=0)] + [
        _src(f"d{i}", str(40 + i), index=i) for i in range(1, 13)
    ]
    out = _emit(group)
    assert len(out) == 13
    assert ("civic", None, None) in out


# --- collapse ---------------------------------------------------------------


def test_a_tower_emits_one_node_carrying_every_unit():
    group = [
        _src(f"u{f}{n}", f"{f}{n:02d}", index=0)
        for f in range(1, 5)
        for n in range(1, 4)
    ]
    out = _emit(group)
    assert len(out) == 1
    _pid, unit, flats = out[0]
    assert unit is None
    assert flats == "101-103;201-203;301-303;401-403"


def test_an_ambiguous_group_collapses_rather_than_exploding():
    # Sequential numbering, 3 m apart — under a door's width. Collapsing is
    # right either way; exploding invents front doors.
    group = [_src(f"u{i}", str(i), index=i, spacing_m=3.0) for i in range(1, 20)]
    out = _emit(group)
    assert len(out) == 1
    assert out[0][2] == "1-19"


# --- tile clipping ----------------------------------------------------------


def test_doors_outside_the_tile_are_left_for_their_own_tile():
    group = [_src(f"d{i}", str(40 + i), index=i) for i in range(1, 13)]
    keep = {"d1", "d2", "d3"}
    out = _emit(group, lambda r: r["address_point_id"] in keep)
    assert {pid for pid, _u, _f in out} == keep


def test_a_tower_whose_representative_is_elsewhere_emits_nothing_here():
    """The collapsed node belongs to exactly one tile, so the others must stay
    silent — otherwise a building straddling a boundary is created twice."""
    group = [
        _src(f"u{f}{n}", f"{f}{n:02d}", index=0)
        for f in range(1, 5)
        for n in range(1, 4)
    ]
    assert _emit(group, _none) == []


def test_a_tower_still_lists_units_that_fall_outside_the_tile():
    """addr:flats describes the building, not the tile, so clipping must not
    reach the listing."""
    group = [
        _src(f"u{f}{n}", f"{f}{n:02d}", index=0)
        for f in range(1, 5)
        for n in range(1, 4)
    ]
    rep = _elect(group)["address_point_id"]
    out = _emit(group, lambda r: r["address_point_id"] == rep)
    assert out[0][2] == "101-103;201-203;301-303;401-403"


# --- degenerate -------------------------------------------------------------


def test_a_group_of_civic_duplicates_passes_every_row_through():
    group = [_src("a", None, index=0), _src("b", None, index=1)]
    out = _emit(group)
    assert len(out) == 2
    assert all(u is None and f is None for _pid, u, f in out)
