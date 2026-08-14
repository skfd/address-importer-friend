"""Local dev runner: python run.py --city-dir <path> [--prod | --env {dev,prod}]"""
import argparse
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the address-importer web UI.")
    parser.add_argument(
        "--city-dir", default=os.environ.get("T2_CITY_DIR") or ".",
        help="Per-city checkout holding config.toml, .env.*, and data/ "
             "(default: $T2_CITY_DIR, else the current directory).",
    )
    parser.add_argument(
        "--env", choices=("dev", "prod"), default="dev",
        help="Which OSM server uploads target (default: dev sandbox).",
    )
    parser.add_argument(
        "--prod", action="store_const", const="prod", dest="env",
        help="Shorthand for --env prod.",
    )
    args = parser.parse_args()

    if os.environ.get("OSM_ENV"):
        print(
            f"note: OSM_ENV is no longer read — use --prod / --env prod. "
            f"Running in {args.env!r} mode.",
            file=sys.stderr,
        )

    city_dir = Path(args.city_dir).resolve()
    if not (city_dir / "config.toml").exists():
        sys.exit(
            f"error: no config.toml in {city_dir} — pass --city-dir pointing "
            "at a per-city checkout (e.g. ../toronto-2-address-import)."
        )
    # Must be set before t2.config is imported: CITY_DIR is computed at module
    # import, and subprocesses spawned by the web app inherit the env var.
    os.environ["T2_CITY_DIR"] = str(city_dir)

    import t2.config
    # Must happen before importing t2.web.app (which pulls in t2.db etc., each
    # of which calls config.load() at import time).
    t2.config.OSM_ENV = args.env
    from t2.web.app import create_app

    print(f"city dir: {city_dir}", file=sys.stderr)
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
