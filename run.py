"""Local dev runner: python run.py [--prod | --env {dev,prod}]"""
import argparse
import os
import sys

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the t2-address-import web UI.")
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

    import t2.config
    # Must happen before importing t2.web.app (which pulls in t2.db etc., each
    # of which calls config.load() at import time).
    t2.config.OSM_ENV = args.env
    from t2.web.app import create_app

    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=True)
