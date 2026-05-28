"""Build a standalone HTML animation of operator review/upload activity over tiles.

Reads `data/tool.db` (events) + `data/tiles.json` (polygons) and writes
`docs/operator-animation.html` — a single page that replays each tile's operator
work in chronological order, compressing idle gaps > 15 minutes.

Usage:
    python -m scripts.build_operator_animation
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "tool.db"
TILES_PATH = ROOT / "data" / "tiles.json"
OUT_PATH = ROOT / "docs" / "operator-animation.html"

REVIEW_KINDS = ("REVIEW_APPROVED", "REVIEW_REJECTED", "REVIEW_OVERRIDE", "REVIEW_CLEARED")
UPLOAD_KIND = "CHANGESET_UPLOADED"
IDLE_GAP_SECONDS = 15 * 60


def run_name_to_tile_id(name: str) -> str:
    m = re.match(r"^(.*?)(?:-batch)?-\d{4}-\d{2}-\d{2}$", name)
    return m.group(1) if m else name


def build_payload() -> dict:
    tiles_by_id = {t["id"]: t for t in json.loads(TILES_PATH.read_text(encoding="utf-8"))["tiles"]}

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Map run_id → tile_id (and pick up name for sidebar).
    run_to_tile: dict[int, str] = {}
    run_meta: dict[int, dict] = {}
    for r in conn.execute("SELECT run_id, name FROM runs").fetchall():
        tid = run_name_to_tile_id(r["name"])
        run_to_tile[int(r["run_id"])] = tid
        run_meta[int(r["run_id"])] = {"tile_id": tid, "run_name": r["name"]}

    # Pull all operator-relevant events in chronological order. CHANGESET_UPLOADED
    # is the terminal action per tile. The four REVIEW_* kinds count as work units.
    placeholders = ",".join("?" * (len(REVIEW_KINDS) + 1))
    rows = conn.execute(
        f"""
        SELECT ts, run_id, event_type
        FROM events
        WHERE event_type IN ({placeholders})
        ORDER BY ts ASC, event_id ASC
        """,
        (*REVIEW_KINDS, UPLOAD_KIND),
    ).fetchall()

    # Aggregate per-tile stats while we walk the timeline.
    tile_stats: dict[str, dict] = {}
    events: list[dict] = []
    for r in rows:
        rid = int(r["run_id"])
        tid = run_to_tile.get(rid)
        if tid is None or tid not in tiles_by_id:
            continue
        kind = "upload" if r["event_type"] == UPLOAD_KIND else "review"
        ts = r["ts"]
        events.append({"t": ts, "tile": tid, "k": kind})
        s = tile_stats.setdefault(tid, {"reviews": 0, "first_ts": ts, "upload_ts": None})
        if kind == "review":
            s["reviews"] += 1
        else:
            s["upload_ts"] = ts

    # Compress idle gaps: replace any gap > IDLE_GAP_SECONDS with a marker so the
    # animation skips overnight quiet periods instead of staring at a frozen map.
    parsed = [(datetime.fromisoformat(e["t"]), e) for e in events]
    gaps: list[dict] = []
    prev_dt = None
    for cur_dt, ev in parsed:
        if prev_dt is not None:
            gap = (cur_dt - prev_dt).total_seconds()
            if gap > IDLE_GAP_SECONDS:
                gaps.append({"from": prev_dt.isoformat(), "to": cur_dt.isoformat(), "seconds": gap})
        prev_dt = cur_dt

    # Reduce polygon payload: keep only id, name, polygon, address_count.
    tile_geom = []
    for tid, t in tiles_by_id.items():
        if tid not in tile_stats:
            continue
        tile_geom.append(
            {
                "id": tid,
                "name": t["name"],
                "addr": t.get("address_count", 0),
                "poly": t["polygon_latlon"],
                "reviews": tile_stats[tid]["reviews"],
                "first_ts": tile_stats[tid]["first_ts"],
                "upload_ts": tile_stats[tid]["upload_ts"],
            }
        )

    return {
        "tiles": tile_geom,
        "events": events,
        "gaps": gaps,
        "idle_gap_seconds": IDLE_GAP_SECONDS,
        "generated_at": datetime.now().astimezone().isoformat(),
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Toronto Address Import — Operator Activity</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html, body { margin: 0; padding: 0; height: 100%; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: #0f1115; color: #eee; }
  #map { position: absolute; inset: 0; }
  .panel {
    position: absolute; top: 12px; left: 12px; z-index: 1000;
    background: rgba(15,17,21,0.92); border: 1px solid #2a2f3a; border-radius: 10px;
    padding: 12px 14px; min-width: 280px; box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    backdrop-filter: blur(6px);
  }
  .panel h1 { font-size: 14px; margin: 0 0 8px; letter-spacing: 0.03em; color: #fff; }
  .stat { display: flex; justify-content: space-between; font-size: 12px; color: #aab; margin: 2px 0; }
  .stat b { color: #fff; font-variant-numeric: tabular-nums; }
  .ts { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; color: #ffd86b; }
  .controls { margin-top: 10px; display: flex; gap: 6px; align-items: center; }
  button { background: #1f2532; color: #eee; border: 1px solid #2a3142; border-radius: 6px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
  button:hover { background: #2a3142; }
  button.primary { background: #3057d4; border-color: #3057d4; }
  button.primary:hover { background: #4068e0; }
  input[type=range] { flex: 1; }
  .speed { font-size: 11px; color: #88a; }
  .legend { font-size: 11px; color: #aab; margin-top: 8px; line-height: 1.4; }
  .legend .swatch { display: inline-block; width: 11px; height: 11px; vertical-align: middle; margin-right: 4px; border: 1px solid #2a2f3a; }
  .scrub { width: 100%; margin-top: 8px; }
  .gap-banner { color: #ff9b6b; font-size: 11px; height: 14px; margin-top: 2px; }
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1>Operator activity — Toronto address import</h1>
  <div class="stat"><span>Time</span><b class="ts" id="time">—</b></div>
  <div class="stat"><span>Session</span><b id="session">—</b></div>
  <div class="stat"><span>Actions taken</span><b id="actions">0</b></div>
  <div class="stat"><span>Tiles in progress</span><b id="inprog">0</b></div>
  <div class="stat"><span>Tiles uploaded</span><b id="done">0</b> / <b id="total">0</b></div>
  <div class="gap-banner" id="gap"></div>
  <input type="range" min="0" max="1000" value="0" class="scrub" id="scrub">
  <div class="controls">
    <button class="primary" id="play">Play</button>
    <button id="restart">Restart</button>
    <span class="speed">Speed</span>
    <select id="speed">
      <option value="100">100×</option>
      <option value="300">300×</option>
      <option value="1000" selected>1000×</option>
      <option value="3000">3000×</option>
      <option value="10000">10000×</option>
    </select>
  </div>
  <div class="legend">
    <div><span class="swatch" style="background:#22273a"></span> Untouched</div>
    <div><span class="swatch" style="background:#f5a623"></span> Reviewing (depth = action count)</div>
    <div><span class="swatch" style="background:#2ecc71"></span> Uploaded to OSM</div>
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = __DATA__;
const IDLE_GAP_S = DATA.idle_gap_seconds;

// Pre-parse timestamps to epoch ms.
DATA.events.forEach(e => e.tms = Date.parse(e.t));
DATA.tiles.forEach(t => { t.first_ms = Date.parse(t.first_ts); t.upload_ms = t.upload_ts ? Date.parse(t.upload_ts) : null; });
const gaps = DATA.gaps.map(g => ({ from: Date.parse(g.from), to: Date.parse(g.to) }));

// Build a "virtual clock" that compresses idle gaps. Each gap becomes 1 second
// of virtual time so the operator's quiet periods don't dominate playback.
const GAP_VIRT_MS = 1500;
function buildClock() {
  const segments = [];
  let virt = 0, prevReal = DATA.events[0].tms;
  segments.push({ realStart: prevReal, virtStart: 0, kind: 'active' });
  for (const g of gaps) {
    segments[segments.length-1].realEnd = g.from;
    segments[segments.length-1].virtEnd = virt + (g.from - segments[segments.length-1].realStart);
    virt = segments[segments.length-1].virtEnd;
    segments.push({ realStart: g.from, realEnd: g.to, virtStart: virt, virtEnd: virt + GAP_VIRT_MS, kind: 'gap' });
    virt += GAP_VIRT_MS;
    segments.push({ realStart: g.to, virtStart: virt, kind: 'active' });
  }
  const last = segments[segments.length-1];
  last.realEnd = DATA.events[DATA.events.length-1].tms;
  last.virtEnd = virt + (last.realEnd - last.realStart);
  return segments;
}
const SEGMENTS = buildClock();
const VIRT_TOTAL_MS = SEGMENTS[SEGMENTS.length-1].virtEnd;

function virtToReal(virtMs) {
  for (const s of SEGMENTS) {
    if (virtMs <= s.virtEnd) {
      if (s.kind === 'gap') return { realMs: s.realStart + (s.realEnd - s.realStart) * ((virtMs - s.virtStart) / (s.virtEnd - s.virtStart)), inGap: s };
      return { realMs: s.realStart + (virtMs - s.virtStart), inGap: null };
    }
  }
  return { realMs: SEGMENTS[SEGMENTS.length-1].realEnd, inGap: null };
}

function realToVirt(realMs) {
  for (const s of SEGMENTS) {
    if (realMs <= (s.realEnd ?? Infinity)) {
      const frac = (realMs - s.realStart) / Math.max(1, (s.realEnd - s.realStart));
      return s.virtStart + frac * (s.virtEnd - s.virtStart);
    }
  }
  return VIRT_TOTAL_MS;
}

// Map.
const map = L.map('map', { zoomControl: true, attributionControl: false }).setView([43.72, -79.40], 11);
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png', { maxZoom: 19, subdomains: 'abcd' }).addTo(map);

// Build a layer per tile.
const tileLayers = new Map();
const tileById = new Map();
DATA.tiles.forEach(t => {
  tileById.set(t.id, t);
  const latlngs = t.poly.map(ring => ring.map(([lat, lon]) => [lat, lon]));
  const layer = L.polygon(latlngs, { color: '#2a2f3a', weight: 1, fillColor: '#22273a', fillOpacity: 0.35, smoothFactor: 1.5 });
  layer.bindTooltip(`<b>${t.name}</b><br>${t.addr} addresses · ${t.reviews} reviews`, { sticky: true });
  layer.addTo(map);
  tileLayers.set(t.id, layer);
});

// Fit bounds once.
const bounds = L.latLngBounds([]);
DATA.tiles.forEach(t => t.poly.forEach(ring => ring.forEach(([lat,lon]) => bounds.extend([lat,lon]))));
if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20] });

// Tile state during playback: counts and final upload flag.
const state = new Map(); // id -> { reviews, uploaded }
function resetState() {
  state.clear();
  DATA.tiles.forEach(t => state.set(t.id, { reviews: 0, uploaded: false, dirty: false }));
  for (const layer of tileLayers.values()) {
    layer.setStyle({ color: '#2a2f3a', weight: 1, fillColor: '#22273a', fillOpacity: 0.35 });
  }
}
resetState();

const styleFor = (s, tile) => {
  if (s.uploaded) return { color: '#2ecc71', weight: 1.4, fillColor: '#2ecc71', fillOpacity: 0.55 };
  if (s.reviews > 0) {
    // Depth of orange based on log of action count (caps around 100).
    const intensity = Math.min(1, Math.log10(1 + s.reviews) / 2);
    const opacity = 0.35 + 0.45 * intensity;
    return { color: '#f5a623', weight: 1.2, fillColor: '#f5a623', fillOpacity: opacity };
  }
  return { color: '#2a2f3a', weight: 1, fillColor: '#22273a', fillOpacity: 0.35 };
};

let eventCursor = 0;
function applyUpTo(realMs) {
  // If we need to go backwards, restart from scratch (cheap enough: ~40k events).
  if (realMs < (DATA.events[Math.max(0, eventCursor-1)]?.tms ?? 0)) {
    resetState();
    eventCursor = 0;
  }
  const dirty = new Set();
  while (eventCursor < DATA.events.length && DATA.events[eventCursor].tms <= realMs) {
    const ev = DATA.events[eventCursor++];
    const s = state.get(ev.tile);
    if (!s) continue;
    if (ev.k === 'review') s.reviews++;
    else s.uploaded = true;
    dirty.add(ev.tile);
  }
  for (const id of dirty) {
    const s = state.get(id);
    const layer = tileLayers.get(id);
    if (layer) layer.setStyle(styleFor(s, tileById.get(id)));
  }
  return dirty.size;
}

const fmt = ms => {
  const d = new Date(ms);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
};

const els = {
  time: document.getElementById('time'),
  session: document.getElementById('session'),
  actions: document.getElementById('actions'),
  inprog: document.getElementById('inprog'),
  done: document.getElementById('done'),
  total: document.getElementById('total'),
  gap: document.getElementById('gap'),
  scrub: document.getElementById('scrub'),
  play: document.getElementById('play'),
  restart: document.getElementById('restart'),
  speed: document.getElementById('speed'),
};
els.total.textContent = DATA.tiles.length;

// Session count = number of active segments.
const sessionsCount = SEGMENTS.filter(s => s.kind === 'active').length;
function currentSession(virtMs) {
  let n = 0;
  for (const s of SEGMENTS) {
    if (s.kind === 'active') n++;
    if (virtMs <= s.virtEnd) return { n, total: sessionsCount, inGap: s.kind === 'gap' ? s : null };
  }
  return { n: sessionsCount, total: sessionsCount, inGap: null };
}

function refreshHud() {
  let done = 0, inprog = 0, actions = 0;
  for (const s of state.values()) {
    if (s.uploaded) done++;
    else if (s.reviews > 0) inprog++;
    actions += s.reviews + (s.uploaded ? 1 : 0);
  }
  els.actions.textContent = actions.toLocaleString();
  els.inprog.textContent = inprog;
  els.done.textContent = done;
}

let virtMs = 0;
let playing = false;
let lastFrameTs = 0;
function setVirt(v) {
  virtMs = Math.max(0, Math.min(VIRT_TOTAL_MS, v));
  const { realMs, inGap } = virtToReal(virtMs);
  applyUpTo(realMs);
  els.time.textContent = fmt(realMs);
  const sess = currentSession(virtMs);
  els.session.textContent = `${sess.n} / ${sess.total}`;
  els.gap.textContent = inGap ? `idle gap — ${fmt(inGap.realStart)} → ${fmt(inGap.realEnd)} (skipped)` : '';
  els.scrub.value = String(Math.round(1000 * virtMs / VIRT_TOTAL_MS));
  refreshHud();
}

function frame(ts) {
  if (!playing) return;
  if (!lastFrameTs) lastFrameTs = ts;
  const dt = ts - lastFrameTs;
  lastFrameTs = ts;
  const speed = Number(els.speed.value);
  setVirt(virtMs + dt * speed);
  if (virtMs >= VIRT_TOTAL_MS) { playing = false; els.play.textContent = 'Play'; return; }
  requestAnimationFrame(frame);
}

els.play.addEventListener('click', () => {
  playing = !playing;
  els.play.textContent = playing ? 'Pause' : 'Play';
  lastFrameTs = 0;
  if (playing) requestAnimationFrame(frame);
});
els.restart.addEventListener('click', () => {
  playing = false; els.play.textContent = 'Play';
  resetState(); eventCursor = 0; setVirt(0);
});
els.scrub.addEventListener('input', e => {
  setVirt(VIRT_TOTAL_MS * Number(e.target.value) / 1000);
});

setVirt(0);
</script>
</body>
</html>
"""


def main() -> int:
    payload = build_payload()
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    OUT_PATH.write_text(html, encoding="utf-8")
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"wrote {OUT_PATH} ({size_kb:.0f} KB)")
    print(f"  tiles: {len(payload['tiles'])}")
    print(f"  events: {len(payload['events'])}")
    print(f"  idle gaps compressed: {len(payload['gaps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
