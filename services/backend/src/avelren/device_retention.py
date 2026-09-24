"""Bounded inactive-device cleanup. Dry-run unless --apply is explicitly supplied."""

import argparse
import json

import psycopg

from .config import settings

MIGRATION = "012_device_retention"
MAX_BATCHES = 20


def run(conn, *, apply: bool = False) -> dict:
    installed = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE version=%s", (MIGRATION,)
    ).fetchone()
    if not installed:
        raise RuntimeError("Device retention migration is not installed")
    total = 0
    initial = None
    remaining = 0
    for _ in range(MAX_BATCHES if apply else 1):
        # Each batch commits independently; an error is loud and prior committed
        # batches are reported as irreversible in the deployment runbook.
        with conn.transaction():
            row = conn.execute(
                "SELECT candidates, deleted FROM prune_inactive_devices(%s)", (apply,)
            ).fetchone()
        candidates, deleted = row
        if initial is None:
            initial = candidates
        total += deleted
        remaining = candidates - deleted
        if not apply or deleted == 0 or remaining == 0:
            break
    return {
        "mode": "apply" if apply else "dry_run",
        "retention_days": 90,
        "candidates": initial,
        "deleted": total,
        "remaining": remaining,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    # Existing notifier credentials; no migrator password and no public endpoint.
    with psycopg.connect(settings.database_dsn, autocommit=True) as conn:
        result = run(conn, apply=args.apply)
    print(json.dumps(result))  # counts only: no IDs, FCM tokens, PINs or DSNs
    if args.apply and result["remaining"]:
        raise SystemExit("Some inactive devices remain; check contention or batch limit")


if __name__ == "__main__":
    main()
