"""
run_webapp.py
--------------
Starts the local QuickCap carbon-copy dashboard (Flask dev server).

This is a local, fake stand-in for the real QuickCap "Request To Login"
admin screens — used to visually verify the automation's field-filling
logic and to give `python main.py --mode local` a safe target. It is not
connected to any real system.

Usage:
    python run_webapp.py
    python run_webapp.py --port 5050
"""

from __future__ import annotations

import argparse
import sys

import config
from webapp.app import app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=config.LOCAL_WEBAPP_HOST)
    parser.add_argument("--port", type=int, default=config.LOCAL_WEBAPP_PORT)
    parser.add_argument("--no-debug", action="store_true",
                         help="Disable Flask's debug/auto-reload error pages.")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/requests"
    print("=" * 70)
    print("QuickCap LOCAL CARBON-COPY DASHBOARD")
    print(f"  {url}")
    print("  Not the real system. Data lives only in "
          "webapp/data/sandbox_state.json.")
    print("  Import sample data:  python import_requests.py "
          "samples/sample_pending_requests.json")
    print("  Stop with Ctrl+C.")
    print("=" * 70)

    try:
        app.run(host=args.host, port=args.port, debug=not args.no_debug,
                 use_reloader=False)
    except OSError as exc:
        print(f"\nCould not start the server on {args.host}:{args.port} "
              f"({exc}). Is it already running, or is the port in use? "
              "Try: python run_webapp.py --port 5051", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()