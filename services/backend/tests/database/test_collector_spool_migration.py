"""Data-only legacy baseline with actual PostgreSQL and durable SQLite recovery."""

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren.collector_replay import ReplayConflict, replay_once
from avelren.collector_spool import SpoolStore
from avelren.collector_spool_migration import migrate_legacy_spool
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse
from avelren.paired_backup_spool import inspect_spool, verify_acked_primary

AT = datetime.now(UTC) - timedelta(days=3)
SOURCE = "4503477f334c72ab05409bf241779592d2fe0bf1"
IMAGE = "sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72"


def result(minute):
    return FetchResult(WorkloadResponse.model_validate({
        "filters": {"countries": [{"id": 1, "name": "Fixture"}]},
        "data": [{"id": 7, "title": "Fixture", "country_id": 1, "for_vehicle_type": 1,
                  "wait_time": minute * 60, "vehicle_in_active_queues_counts": minute + 1}],
    }), 200, minute + 10, str(minute + 1) * 64, None)


async def baseline(path, database):
    store = SpoolStore(path)
    async with AsyncConnectionPool(
        database("collector"), open=False, kwargs={"row_factory": dict_row},
    ) as pool:
        for minute in range(5):
            store.finish(store.begin(AT + timedelta(minutes=minute)), result(minute), 1)
            if minute < 4:
                await replay_once(store, pool, AT + timedelta(minutes=10), prune_acked=False)
        store.begin(AT + timedelta(minutes=5))
    with psycopg.connect(database("admin")) as conn:
        conn.execute("UPDATE observations SET wait_time_status=DEFAULT WHERE time<%s",
                     (AT + timedelta(minutes=3),))
    # 1 aged ACK, 2 unaged ACK, 3 committed-pending legacy, 4 modern ACK,
    # 5 pending absent SQL, 6 interrupted started.
    store.conn.execute("UPDATE cycles SET acked_at=? WHERE seq=1", (AT.isoformat(),))
    store.conn.execute("UPDATE cycles SET state='pending',acked_at=NULL WHERE seq=3")
    store.close()


async def migrate(path, database):
    store = SpoolStore(path)
    try:
        async with await psycopg.AsyncConnection.connect(
            database("collector"), row_factory=dict_row,
        ) as conn:
            return await migrate_legacy_spool(store, conn, source_commit=SOURCE, image_id=IMAGE)
    finally:
        store.close()


def snapshot_sql(database):
    with psycopg.connect(database("admin")) as conn:
        return tuple(conn.execute(f"SELECT * FROM {table} ORDER BY time").fetchall()
                     for table in ("collector_runs", "observations"))


def recovery_module():
    path = Path(__file__).resolve().parents[4] / "ops/paired-restore-acceptance.py"
    spec = importlib.util.spec_from_file_location("migration_recovery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_sql_cycles_and_restarts_with_strict_restore(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(baseline(path, database))
    before_sql = snapshot_sql(database)
    store = SpoolStore(path)
    before_cycles = store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall()
    store.close()
    expected = {"legacy_verified": 3, "modern_verified": 1, "pending_uncommitted": 1,
                "started_preserved": 1}
    assert asyncio.run(migrate(path, database)) == expected
    assert snapshot_sql(database) == before_sql
    assert asyncio.run(migrate(path, database)) == expected
    store = SpoolStore(path)
    assert store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall() == before_cycles
    store.backup_to(tmp_path / "static.sqlite3")
    assert inspect_spool(tmp_path / "static.sqlite3")["state_counts"] == {
        "acked": 3, "pending": 2, "started": 1,
    }
    evidence = asyncio.run(recovery_module().recover_pair(store, database("collector")))
    assert evidence["replayed_sequences"] == [3, 5, 6]
    assert evidence["verified_cycles"] == 6
    assert store.conn.execute("SELECT * FROM cycles WHERE seq=1").fetchone() == before_cycles[0]
    store.close()
    after_sql = snapshot_sql(database)
    assert after_sql[0][:4] == before_sql[0]
    assert after_sql[1][:4] == before_sql[1]


@pytest.mark.parametrize("damage", ["status_null", "status_missing", "seconds", "missing_run",
                                   "extra_observation", "body", "later_row"])
def test_late_mismatch_rolls_back_all_markers_without_sql_writes(database, tmp_path, damage):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(baseline(path, database))
    with psycopg.connect(database("admin")) as conn:
        at = AT + timedelta(minutes=2) if damage == "later_row" else AT
        if damage in {"status_null", "status_missing"}:
            conn.execute("UPDATE observations SET wait_time_status=%s WHERE time=%s",
                         (None if damage == "status_null" else "missing", at))
        elif damage == "missing_run":
            conn.execute("DELETE FROM collector_runs WHERE time=%s", (at,))
        elif damage == "extra_observation":
            conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(8,'Extra',1)")
            conn.execute("INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
                         "vehicles_in_queue,is_paused) VALUES(%s,8,0,0,false)", (at,))
        elif damage == "body":
            conn.execute("UPDATE collector_runs SET body_sha256=%s WHERE time=%s", ("f" * 64, at))
        else:
            conn.execute("UPDATE observations SET wait_time_seconds=999 WHERE time=%s", (at,))
    before_sql = snapshot_sql(database)
    store = SpoolStore(path)
    before = store.conn.execute("SELECT * FROM cycles").fetchall()
    store.close()
    with pytest.raises(ReplayConflict):
        asyncio.run(migrate(path, database))
    store = SpoolStore(path)
    assert store.conn.execute("SELECT * FROM cycles").fetchall() == before
    assert not store.conn.execute(
        "SELECT * FROM meta WHERE key LIKE 'legacy_verified:%'"
    ).fetchall()
    assert snapshot_sql(database) == before_sql
    store.close()


def test_marker_does_not_hide_sql_changes_and_prune_cleans_marker(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(baseline(path, database))
    asyncio.run(migrate(path, database))
    with psycopg.connect(database("admin")) as conn:
        conn.execute("UPDATE observations SET wait_time_seconds=999 WHERE time=%s", (AT,))
    store = SpoolStore(path)

    async def verify():
        async with await psycopg.AsyncConnection.connect(
            database("collector"), row_factory=dict_row,
        ) as conn:
            await verify_acked_primary(store, conn)

    with pytest.raises(ReplayConflict):
        asyncio.run(verify())
    store.prune_acked(datetime.now(UTC))
    assert store._meta("legacy_verified:1") is None
    assert store._meta("legacy_verified:2") is not None
    store.close()


def test_1439_aged_legacy_acks_migrate_atomically_and_prune_naturally(database, tmp_path):
    """Match the recorded retained ACK count using synthetic primary payloads."""
    count = 1439
    path = tmp_path / "spool.sqlite3"
    store = SpoolStore(path)
    runs, observations = [], []
    for minute in range(count):
        at = AT + timedelta(minutes=minute)
        fetched = result(minute % 5)
        seq = store.begin(at)
        store.finish(seq, fetched, 1)
        store.ack(seq)
        item = fetched.response.data[0]
        runs.append((at, fetched.http_status, fetched.duration_ms,
                     fetched.body_sha256, 1, fetched.error))
        observations.append((at, item.id, item.wait_time,
                             item.vehicles_in_queue, item.is_paused))
    store.conn.execute("UPDATE cycles SET acked_at=at")
    before_cycles = store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall()
    store.close()
    with psycopg.connect(database("admin")) as conn:
        conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(7,'Fixture',1)")
        conn.cursor().executemany(
            "INSERT INTO collector_runs(time,http_status,duration_ms,body_sha256,"
            "rows_written,error) "
            "VALUES(%s,%s,%s,%s,%s,%s)", runs,
        )
        conn.cursor().executemany(
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
            "vehicles_in_queue,is_paused) VALUES(%s,%s,%s,%s,%s)", observations,
        )
        # A failure at the final retained cycle must undo all preceding markers.
        conn.execute("UPDATE observations SET wait_time_seconds=999 WHERE time=%s", (runs[-1][0],))
    damaged_sql = snapshot_sql(database)
    with pytest.raises(ReplayConflict):
        asyncio.run(migrate(path, database))
    store = SpoolStore(path)
    assert store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall() == before_cycles
    assert not store.conn.execute(
        "SELECT * FROM meta WHERE key LIKE 'legacy_verified:%'"
    ).fetchall()
    store.close()
    assert snapshot_sql(database) == damaged_sql
    with psycopg.connect(database("admin")) as conn:
        conn.execute("UPDATE observations SET wait_time_seconds=%s WHERE time=%s",
                     (observations[-1][2], runs[-1][0]))
    before_sql = snapshot_sql(database)
    assert asyncio.run(migrate(path, database)) == {
        "legacy_verified": count, "modern_verified": 0, "pending_uncommitted": 0,
        "started_preserved": 0,
    }
    store = SpoolStore(path)
    assert store.conn.execute("SELECT * FROM cycles ORDER BY seq").fetchall() == before_cycles
    assert store.conn.execute(
        "SELECT count(*) FROM meta WHERE key LIKE 'legacy_verified:%'"
    ).fetchone()[0] == count

    async def verify():
        async with await psycopg.AsyncConnection.connect(
            database("collector"), row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as conn:
            return await verify_acked_primary(store, conn)

    assert asyncio.run(verify()) == {"acked_cycles": count, "acked_observations": count}
    assert snapshot_sql(database) == before_sql
    # The first normal retention pass removes the aged cycles and their markers.
    # A new interrupted capture remains available for modern recovery.
    retained = store.begin(datetime.now(UTC))
    retained_row = store.conn.execute("SELECT * FROM cycles WHERE seq=?", (retained,)).fetchone()
    store.prune_acked(datetime.now(UTC))
    assert store.conn.execute("SELECT * FROM cycles").fetchall() == [retained_row]
    assert not store.conn.execute(
        "SELECT * FROM meta WHERE key LIKE 'legacy_verified:%'"
    ).fetchall()
    store.backup_to(tmp_path / "pruned.sqlite3")
    assert inspect_spool(tmp_path / "pruned.sqlite3")["state_counts"] == {
        "acked": 0, "pending": 0, "started": 1,
    }
    store.close()
    assert snapshot_sql(database) == before_sql
