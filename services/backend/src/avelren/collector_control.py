"""Operator-only local capture-mode control; no network endpoint."""

import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .collector_spool import SpoolStore

SPOOL_PATH = Path("/var/lib/avelren/collector-spool/cycles.sqlite3")


def _serialize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальний режим collector")
    parser.add_argument("command", choices=["capture-only"])
    parser.add_argument("action", choices=["on", "off", "status"])
    args = parser.parse_args(argv)
    store = SpoolStore(SPOOL_PATH)
    try:
        if args.action == "status":
            print(json.dumps(asdict(store.status()), default=_serialize, ensure_ascii=False))
            return 0
        requested = args.action == "on"
        store.set_capture_only(requested)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = store.status()
            if status.capture_only == requested and status.mode_ack is requested:
                print(json.dumps(asdict(status), default=_serialize, ensure_ascii=False))
                return 0
            time.sleep(0.25)
        print("collector did not acknowledge mode within 30 seconds")
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
