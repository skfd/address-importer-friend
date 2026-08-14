"""Materialize a synthetic city checkout before any t2 module is imported.

The engine repo deliberately carries no config.toml — city config lives in a
per-city checkout selected via T2_CITY_DIR. Several t2 modules call
config.load() at import time, so tests need a city dir to exist at collection.
Always a fresh temp dir (any T2_CITY_DIR from the shell is overridden), so the
suite can never touch a real checkout's data.
"""
import os
import shutil
import tempfile
from pathlib import Path

_city = Path(tempfile.mkdtemp(prefix="t2-test-city-"))
shutil.copy(
    Path(__file__).resolve().parents[1] / "config.example.toml",
    _city / "config.toml",
)
os.environ["T2_CITY_DIR"] = str(_city)
