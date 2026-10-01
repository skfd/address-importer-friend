"""Building outlines from the OSM extract, for judging unit groups by what
they sit in.

The address extract (`osm_refresh`) keeps only objects carrying an address,
and most of the buildings a townhouse complex is made of carry none. The
unit-shape auto-judge needs all of them: whether a group's units land one or
two to a small building, or by the dozen in one large one, is the difference
between a townhouse complex and an apartment block that the unit numbering
cannot see.

Read from the same Ontario PBF the refresh downloaded, filtered to the city
bbox, and cached beside the extract as `<extract stem>-buildings.json`.
Rebuilt when the PBF is newer than the cache. Outlines are outer rings only;
a courtyard building's hole is ignored, which overstates its area and can
only push a group toward "apartment", the conservative side.
"""
import json
import math
from collections import defaultdict
from pathlib import Path

# Metres per degree near the city. Good to well under a percent over a
# city's extent, which is all an area and a point-in-ring need.
_M_PER_DEG_LAT = 110_574.0

# A unit point this close outside an outline is taken to be in it: the City
# places some unit points on the wall line, or just past it at the door.
NEAR_M = 3.0

_CELL_M = 100.0


def cache_path(cfg) -> Path:
    ext = Path(cfg.osm_extract_json)
    return ext.with_name(f"{ext.stem}-buildings.json")


def pbf_path(cfg) -> Path:
    return Path(cfg.osm_extract_json).with_name("ontario-latest.osm.pbf")


def extract(pbf: Path, bbox: tuple[float, float, float, float]) -> list[dict]:
    """Every building area in bbox (minlat, minlon, maxlat, maxlon):
    {id, type, building, levels, ring: [[lat, lon], ...]} per outer ring."""
    import osmium  # lazily, so the web app doesn't pay for it

    s, w, n, e = bbox
    out: list[dict] = []

    class Handler(osmium.SimpleHandler):
        def area(self, a):
            kind = a.tags.get("building")
            if not kind:
                return
            try:
                rings = [[[nd.lat, nd.lon] for nd in ring] for ring in a.outer_rings()]
            except Exception:  # an unassemblable multipolygon; nothing to place
                return
            for ring in rings:
                lats = [p[0] for p in ring]
                lons = [p[1] for p in ring]
                if max(lats) < s or min(lats) > n or max(lons) < w or min(lons) > e:
                    continue
                out.append({
                    "id": a.orig_id(),
                    "type": "way" if a.from_way() else "relation",
                    "building": kind,
                    "levels": a.tags.get("building:levels"),
                    "ring": ring,
                })

    Handler().apply_file(str(pbf), locations=True)
    return out


def load(cfg, rebuild: bool = False) -> list[dict]:
    """The cached outlines, extracted first if missing, stale or asked for."""
    cache, pbf = cache_path(cfg), pbf_path(cfg)
    if rebuild or not cache.exists() or (pbf.exists() and pbf.stat().st_mtime > cache.stat().st_mtime):
        if not pbf.exists():
            raise FileNotFoundError(f"{pbf} missing; refresh the OSM extract first")
        cache.write_text(json.dumps(extract(pbf, cfg.osm_city_bbox)), encoding="utf-8")
    return json.loads(cache.read_text(encoding="utf-8"))


class Index:
    """Point -> containing building, on a local metric plane."""

    def __init__(self, buildings: list[dict]):
        lats = [p[0] for b in buildings for p in b["ring"]] or [0.0]
        self._lat0 = (min(lats) + max(lats)) / 2
        self._kx = _M_PER_DEG_LAT * math.cos(math.radians(self._lat0))
        self._grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
        for b in buildings:
            poly = [self._xy(lat, lon) for lat, lon in b["ring"]]
            if len(poly) < 3:
                continue
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            rec = {**b, "poly": poly, "bb": (min(xs), min(ys), max(xs), max(ys)), "area": _area(poly)}
            for gx in range(int(rec["bb"][0] // _CELL_M), int(rec["bb"][2] // _CELL_M) + 1):
                for gy in range(int(rec["bb"][1] // _CELL_M), int(rec["bb"][3] // _CELL_M) + 1):
                    self._grid[(gx, gy)].append(rec)

    def _xy(self, lat: float, lon: float) -> tuple[float, float]:
        return lon * self._kx, lat * _M_PER_DEG_LAT

    def at(self, lat: float, lon: float, near_m: float = NEAR_M) -> dict | None:
        """The building containing the point; failing that, the nearest one
        whose outline is within `near_m`; else None. Smallest wins a tie of
        containment, so a garage inside a mapped lot outline does not lose to
        the lot."""
        x, y = self._xy(lat, lon)
        cx, cy = int(x // _CELL_M), int(y // _CELL_M)
        seen: set[int] = set()
        inside, near = [], []
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for b in self._grid.get((gx, gy), ()):
                    if id(b) in seen:
                        continue
                    seen.add(id(b))
                    x0, y0, x1, y1 = b["bb"]
                    if x < x0 - near_m or x > x1 + near_m or y < y0 - near_m or y > y1 + near_m:
                        continue
                    if _contains(b["poly"], x, y):
                        inside.append(b)
                    else:
                        d = _edge_distance(b["poly"], x, y)
                        if d <= near_m:
                            near.append((d, b))
        if inside:
            return min(inside, key=lambda b: b["area"])
        if near:
            return min(near, key=lambda t: t[0])[1]
        return None


def _area(poly) -> float:
    return abs(sum(poly[i][0] * poly[i - 1][1] - poly[i - 1][0] * poly[i][1] for i in range(len(poly)))) / 2


def _contains(poly, x: float, y: float) -> bool:
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _edge_distance(poly, x: float, y: float) -> float:
    best = math.inf
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i - 1], poly[i]
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best
