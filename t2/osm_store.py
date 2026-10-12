"""The shared OSM extract store, as this repo reads it.

The Ontario PBF is not ours to download. ``osm-extracts`` (a sibling checkout,
``~/Code/osm-extracts``) keeps one copy for every project under ``~/Code`` in
``OSM_DATA_DIR`` (default ``~/Code/.osm-data``), one directory per region:

    ontario/ontario-2026-10-02.osm.pbf     dated, immutable
    ontario/ontario-2026-10-02.meta.json   source_url, source_last_modified, bytes, sha256
    ontario/latest.json                    the newest file's meta plus "file"

``cfg.osm_pbf_url`` still declares which extract a city needs; its basename
names the region (``ontario-latest.osm.pbf`` -> ``ontario``). A city's
``meta.json`` records the dated file it was filtered from, and every later
pass over the PBF (building outlines) reopens that same file so the passes
agree. The store keeps 14 days of files plus the newest two and pins, so the recorded one can
be pruned; then we fall back to the latest and say the city wants a refresh.

Standard library only, so the web app and ``osm_buildings`` stay light.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def store_dir() -> Path:
    return Path(os.environ.get("OSM_DATA_DIR") or Path.home() / "Code" / ".osm-data")


def tool_path() -> Path:
    return Path(os.environ.get("OSM_EXTRACTS_TOOL")
                or Path.home() / "Code" / "osm-extracts" / "osm_extracts.py")


def region_from_url(url: str) -> str:
    """The store's region for a Geofabrik URL — the same rule the tool uses."""
    name = url.rstrip("/").rsplit("/", 1)[-1]
    for suffix in ("-latest.osm.pbf", ".osm.pbf"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    raise ValueError(f"cannot name an OSM store region from {url}")


def region_dir(cfg) -> Path:
    return store_dir() / region_from_url(cfg.osm_pbf_url)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_latest(cfg) -> dict | None:
    """``latest.json`` for the city's region, or None if nothing is stored yet."""
    return _read_json(region_dir(cfg) / "latest.json")


def file_meta(pbf: Path) -> dict:
    """The store's sidecar for one dated file (``<name>.meta.json``)."""
    return _read_json(pbf.with_name(pbf.name[: -len(".osm.pbf")] + ".meta.json")) or {}


def fetch(cfg, force: bool = False) -> None:
    """Have the store refresh the city's extract. The tool HEAD-checks Geofabrik
    and downloads only on a change (``--force`` regardless), under its own lock.
    Its output goes to our stdout, so it lands in the refresh log."""
    tool = tool_path()
    if not tool.exists():
        raise FileNotFoundError(
            f"{tool} missing; clone osm-extracts there or set OSM_EXTRACTS_TOOL"
        )
    args = [sys.executable, str(tool), "fetch", "--url", cfg.osm_pbf_url]
    if force:
        args.append("--force")
    sys.stdout.flush()
    subprocess.run(args, check=True)


def resolve_pbf(cfg, meta: dict | None) -> tuple[Path | None, str | None]:
    """The PBF a city extract was filtered from: (path, note).

    ``meta["pbf_file"]`` first; a meta from before the store has only
    ``pbf_sha256``, matched against the store's sidecars; failing both, the
    latest file, with a note saying so. (None, note) when nothing is stored.
    """
    d = region_dir(cfg)
    meta = meta or {}
    name = meta.get("pbf_file")
    if name and (d / name).exists():
        return d / name, None
    sha = meta.get("pbf_sha256")
    if sha and d.exists():
        for side in sorted(d.glob("*.meta.json")):
            if (_read_json(side) or {}).get("sha256") == sha:
                pbf = side.with_name(side.name[: -len(".meta.json")] + ".osm.pbf")
                if pbf.exists():
                    return pbf, None
    latest = read_latest(cfg) or {}
    pbf = d / latest["file"] if latest.get("file") else None
    if pbf is None or not pbf.exists():
        return None, f"no {d.name} extract in {store_dir()}; refresh the OSM extract first"
    if name or sha:
        recorded = name or f"sha256 {sha[:16]}…"
        return pbf, (f"{recorded} is no longer in the store; using {pbf.name}. "
                     "Refresh the OSM extract so every pass reads the same snapshot.")
    return pbf, None


def city_pbf(cfg, meta: dict | None = None) -> tuple[Path | None, str | None]:
    """resolve_pbf for the city's own extract; reads its meta.json unless given."""
    if meta is None:
        meta = _read_json(cfg.osm_extract_dir / "meta.json")
    return resolve_pbf(cfg, meta)
