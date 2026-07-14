"""
import_requests.py
-------------------
Loads JSON files of pending "Request To Login" records into the local
carbon-copy dashboard's sandbox queue (webapp/data/sandbox_state.json), so
you can open http://127.0.0.1:5050/requests and see them, or run the
automation against them with `python main.py --mode local`.

Each JSON file must contain a list of objects. See
samples/sample_pending_requests.json for the field names and three worked
scenarios (multi-organization popup, duplicate email, clean approve).
Unknown fields are ignored; a record without "token_no" is skipped.

Usage:
    python import_requests.py samples\\sample_pending_requests.json
    python import_requests.py data\\import\\*.json
    python import_requests.py --reset samples\\sample_pending_requests.json
    python import_requests.py --reset          # just clears the sandbox
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from webapp import store


def load_records(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of request objects.")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files", nargs="*",
        help="JSON file(s) to import. Supports glob patterns. If omitted, "
             "imports every *.json file in data/import/.")
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear the sandbox queue first (instead of merging by token_no).")
    args = parser.parse_args()

    if args.reset and not args.files:
        store.reset_sandbox()
        print("Sandbox cleared.")
        return

    if args.reset:
        store.reset_sandbox()
        print("Sandbox cleared.")

    paths: list[Path] = []
    if args.files:
        for pattern in args.files:
            matches = glob.glob(pattern)
            if matches:
                paths.extend(Path(m) for m in matches)
            else:
                paths.append(Path(pattern))
    else:
        import config
        paths = sorted(config.IMPORT_DIR.glob("*.json"))
        if not paths:
            print(f"No .json files found in {config.IMPORT_DIR}. "
                  "Pass a file path explicitly, e.g.:\n"
                  "  python import_requests.py samples/sample_pending_requests.json")
            sys.exit(1)

    total = 0
    for path in paths:
        if not path.exists():
            print(f"  ! Skipping {path} (not found)")
            continue
        try:
            records = load_records(path)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"  ! Skipping {path}: {exc}")
            continue
        count = store.import_requests(records, replace=False)
        print(f"  + Imported {count} request(s) from {path}")
        total += count

    import config
    print(f"\nDone. {total} request(s) imported. "
          f"Sandbox now has {len(store.get_requests())} total.")
    print(f"View them at {config.LOCAL_WEBAPP_REQUEST_LIST_URL} "
          "(start the server first with `python run_webapp.py` if it "
          "isn't running).")


if __name__ == "__main__":
    main()