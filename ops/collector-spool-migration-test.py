"""Disposable fixture helper: data-only legacy spool, never an old-image claim.

The fixture already ran its historical writer against synthetic HTTP. Read that
writer's SQL row without changing SQL, reconstruct a matching ACK, and exercise
the explicit migration using the audited historical contract as test provenance.
This file is a test driver and is never installed as a production adapter.
"""

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
from avelren.collector_spool import SpoolStore
from avelren.collector_spool_migration import migrate_legacy_spool
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse
from psycopg.rows import dict_row


async def seed_legacy(path, dsn, acked_age_hours):
    store = SpoolStore(path)
    try:
        if store.conn.execute("SELECT count(*) FROM cycles").fetchone()[0]:
            raise ValueError("fixture_seed_requires_empty_spool")
        async with await psycopg.AsyncConnection.connect(
            dsn, row_factory=dict_row, options="-c default_transaction_read_only=on",
        ) as conn:
            run = await (await conn.execute(
                "SELECT time,http_status,duration_ms,body_sha256,rows_written,error "
                "FROM collector_runs ORDER BY time LIMIT 1"
            )).fetchone()
            if run is None:
                raise ValueError("fixture_requires_historical_run")
            rows = await (await conn.execute(
                "SELECT o.checkpoint_id,o.wait_time_seconds,o.wait_time_status,"
                "o.vehicles_in_queue,o.is_paused,c.title,c.country_id,c.for_vehicle_type "
                "FROM observations o JOIN checkpoints c ON c.id=o.checkpoint_id "
                "WHERE o.time=%s ORDER BY o.checkpoint_id", (run["time"],),
            )).fetchall()
        if len(rows) != run["rows_written"] or any(
            row["wait_time_status"] != "legacy_unknown" for row in rows
        ):
            raise ValueError("fixture_requires_exact_legacy_primary")
        response = WorkloadResponse.model_validate({"data": [{
            "id": row["checkpoint_id"], "title": row["title"],
            "country_id": row["country_id"], "for_vehicle_type": row["for_vehicle_type"],
            "wait_time": row["wait_time_seconds"],
            "vehicle_in_active_queues_counts": row["vehicles_in_queue"],
            "is_paused": row["is_paused"],
        } for row in rows]})
        seq = store.begin(run["time"])
        store.finish(seq, FetchResult(response, run["http_status"], run["duration_ms"],
                                      run["body_sha256"], run["error"]), 1)
        store.ack(seq)
        acked_at = datetime.now(UTC) - timedelta(hours=acked_age_hours)
        if acked_at < run["time"]:
            # Synthetic historical timestamps are current; age cannot precede capture.
            acked_at = run["time"]
        store.conn.execute("UPDATE cycles SET acked_at=? WHERE seq=?",
                           (acked_at.isoformat(), seq))
        pending_at = run["time"] + timedelta(microseconds=1)
        store.finish(store.begin(pending_at), FetchResult(None, None, 0, None,
                                                        "synthetic pending outage"), 1)
        store.begin(run["time"] + timedelta(microseconds=2))
        return {"fixture_provenance": "synthetic_data_only_legacy_contract",
                "seeded_cycles": 3, "seeded_observations": len(rows),
                "states": {"acked": 1, "pending": 1, "started": 1}}
    finally:
        store.close()


async def migrate_fixture(path, dsn, source_commit, image_id, fixture_image_id, source_sha256):
    if (not re.fullmatch(r"[0-9a-f]{40}", source_commit or "")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id or "")
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", fixture_image_id or "")
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256 or "")
            or fixture_image_id == image_id):
        raise ValueError("fixture_requires_distinct_explicit_provenance")
    store = SpoolStore(path)
    try:
        before = store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall()
        async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
            counts = await migrate_legacy_spool(
                store, conn, source_commit=source_commit, image_id=image_id,
            )
        if store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall() != before:
            raise AssertionError("fixture_migration_changed_cycles")
        return {"fixture_provenance": "synthetic_data_only_legacy_contract",
                "audited_contract_source_commit": source_commit,
                "audited_contract_image_id": image_id,
                "actual_fixture_image_id": fixture_image_id,
                "actual_legacy_source_sha256": source_sha256, **counts}
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "seed-legacy", "migrate-fixture"))
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--acked-age-hours", type=float, default=0)
    parser.add_argument("--audited-source-commit")
    parser.add_argument("--audited-image-id")
    parser.add_argument("--fixture-image-id")
    parser.add_argument("--legacy-source-sha256")
    args = parser.parse_args()
    if args.command == "init":
        SpoolStore(args.spool).close()
        result = {"initialized": True}
    else:
        dsn = os.environ["DATABASE_URL"]
        result = asyncio.run(seed_legacy(args.spool, dsn, args.acked_age_hours)
                             if args.command == "seed-legacy"
                             else migrate_fixture(args.spool, dsn, args.audited_source_commit,
                                                  args.audited_image_id, args.fixture_image_id,
                                                  args.legacy_source_sha256))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
