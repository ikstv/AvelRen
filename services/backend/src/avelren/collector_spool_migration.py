"""Explicit stopped-writer migration; preserve SQL and every retained cycle.

Metadata records the exact legacy primary contract already checked against SQL.
Consumers check the binding and independently compare SQL again. Merely opening
a spool never grants legacy semantics to unmarked ACKs or later capture.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .collector_replay import ReplayConflict, verify_committed_cycle
from .collector_spool import CapturedCycle, SpoolStore, _canonical

# These are the existing audited writer identities, as exact pairs.
LEGACY_WRITERS = frozenset({
    ("4503477f334c72ab05409bf241779592d2fe0bf1",
     "sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72"),
    ("a4a16b64147fcf28c6245f2032a61279ca7c74ec",
     "sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3"),
    ("dedf49fcc0b13ddf85bfacaf3cdb1ef71d3db64d",
     "sha256:64b375cc6a7192ca5f9051bf2217c246d667d993c426ed4a1f3a92957c7375db"),
})


def legacy_marker(row, cycle: CapturedCycle, source_commit: str, image_id: str) -> str:
    if (source_commit, image_id) not in LEGACY_WRITERS:
        raise ValueError("legacy_writer_unrecognized")
    primary = {
        "at": cycle.at.isoformat(),
        "run": [cycle.http_status, cycle.duration_ms, cycle.body_sha256,
                len(cycle.items), cycle.error],
        "observations": sorted(
            (item.id, item.wait_time if item.wait_time is not None else 0,
             "legacy_unknown", item.vehicles_in_queue, item.is_paused)
            for item in cycle.items
        ),
    }
    return _canonical({
        "version": 1, "source_commit": source_commit, "image_id": image_id,
        "seq": row[0], "at": row[1], "payload_version": row[2], "payload_sha256": row[4],
        "primary_sha256": hashlib.sha256(_canonical(primary)).hexdigest(),
    }).decode()


def migrated_legacy_cycle(store: SpoolStore, cycle: CapturedCycle) -> bool:
    value = store._meta(f"legacy_verified:{cycle.seq}")
    if value is None:
        return False
    row = store.conn.execute(
        "SELECT seq,at,payload_version,payload,payload_sha256 FROM cycles WHERE seq=?",
        (cycle.seq,),
    ).fetchone()
    _validate_marker(row, cycle, value)
    return True


def _validate_marker(row, cycle, value):
    from .paired_backup_spool import _unique_object, decode_cycle
    try:
        marker = json.loads(value, object_pairs_hook=_unique_object)
        if row is None or decode_cycle(row) != cycle or legacy_marker(
            row, cycle, marker["source_commit"], marker["image_id"],
        ) != _canonical(marker).decode():
            raise ValueError
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("legacy_marker_invalid") from exc


def validate_legacy_markers(connection):
    from .paired_backup_spool import decode_cycle

    for key, value in connection.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'legacy_verified:%'"
    ).fetchall():
        seq = key.removeprefix("legacy_verified:")
        if not seq.isascii() or not seq.isdecimal() or str(int(seq)) != seq or int(seq) < 1:
            raise ValueError("legacy_marker_invalid")
        row = connection.execute(
            "SELECT seq,at,payload_version,payload,payload_sha256,state FROM cycles WHERE seq=?",
            (int(seq),),
        ).fetchone()
        if row is None or row[5] not in {"acked", "pending"}:
            raise ValueError("legacy_marker_invalid")
        _validate_marker(row[:5], decode_cycle(row[:5]), value)


async def migrate_legacy_spool(
    store: SpoolStore, conn: AsyncConnection, *, source_commit: str, image_id: str,
) -> dict:
    """Caller stops the writer first; SQLite lock makes metadata commit atomic.

    PostgreSQL access is SELECT only. A committed pending cycle receives the same
    proof as an ACK, so a pre-upgrade commit-before-ACK crash can resume safely.
    Uncommitted pending and started cycles retain modern replay behavior.
    """
    if (source_commit, image_id) not in LEGACY_WRITERS:
        raise ValueError("legacy_writer_unrecognized")
    counts = {"legacy_verified": 0, "modern_verified": 0, "pending_uncommitted": 0,
              "started_preserved": 0}
    async with conn.transaction():
        await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return await _migrate_locked(store, conn, source_commit, image_id, counts)


async def _migrate_locked(store, conn, source_commit, image_id, counts):
    from .paired_backup_spool import decode_cycle

    with store._transaction():
        validate_legacy_markers(store.conn)
        markers = []
        for row in store.conn.execute(
            "SELECT seq,at,payload_version,payload,payload_sha256,state FROM cycles ORDER BY seq"
        ).fetchall():
            if row[5] == "started":
                counts["started_preserved"] += 1
                continue
            cycle = decode_cycle(row[:5])
            exists = await (await conn.execute(
                "SELECT time FROM collector_runs WHERE time=%s", (cycle.at,),
            )).fetchone()
            if exists is None and row[5] == "pending":
                if migrated_legacy_cycle(store, cycle):
                    raise ReplayConflict("migrated legacy primary missing")
                counts["pending_uncommitted"] += 1
                continue
            if migrated_legacy_cycle(store, cycle):
                await verify_committed_cycle(conn, cycle, legacy_unknown=True)
                counts["legacy_verified"] += 1
                continue
            try:
                await verify_committed_cycle(conn, cycle)
                counts["modern_verified"] += 1
            except ReplayConflict:
                await verify_committed_cycle(conn, cycle, legacy_unknown=True)
                markers.append((f"legacy_verified:{cycle.seq}",
                                legacy_marker(row, cycle, source_commit, image_id)))
                counts["legacy_verified"] += 1
        store.conn.executemany("INSERT INTO meta(key,value) VALUES (?,?)", markers)
    return counts


async def _run(args):
    if not args.spool.is_file() or args.spool.is_symlink():
        raise ValueError("spool_missing_or_unsafe")
    from .paired_backup_spool import inspect_spool

    inspect_spool(args.spool)
    # The coordinator must hold its stopped-writer lease for this whole call.
    store = SpoolStore(args.spool)
    try:
        async with await AsyncConnection.connect(
            os.environ["DATABASE_URL"], row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as conn:
            return await migrate_legacy_spool(
                store, conn, source_commit=args.source_commit, image_id=args.image_id,
            )
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--image-id", required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(_run(args))
    except Exception:
        parser.exit(1, "legacy_spool_migration_failed\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
