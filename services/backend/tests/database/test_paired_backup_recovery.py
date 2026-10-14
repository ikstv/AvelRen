"""Exact pair acceptance against disposable PostgreSQL; no source traffic."""

import asyncio
import gzip
import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import paired_backup_spool
from avelren.collector_replay import ReplayConflict, replay_once
from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse

AT = datetime.now(UTC) - timedelta(days=3)
ROOT = Path(__file__).resolve().parents[4]


def result(minute):
    return FetchResult(
        WorkloadResponse.model_validate(
            {
                "filters": {"countries": [{"id": 1, "name": "Synthetic"}]},
                "data": [
                    {
                        "id": 7,
                        "title": "Synthetic truck",
                        "country_id": 1,
                        "for_vehicle_type": 1,
                        "wait_time": minute * 60,
                        "vehicle_in_active_queues_counts": minute + 1,
                        "is_paused": minute == 1,
                    }
                ],
            }
        ),
        200,
        minute + 9,
        str(minute + 1) * 64,
        None,
    )


async def mixed_fixture(path, dsn):
    store = SpoolStore(path)
    async with AsyncConnectionPool(dsn, open=False, kwargs={"row_factory": dict_row}) as pool:
        for minute in range(5):
            store.finish(store.begin(AT + timedelta(minutes=minute)), result(minute), 1)
            if minute < 2:
                await replay_once(store, pool, AT + timedelta(minutes=10))
        store.begin(AT + timedelta(minutes=5))
    # Historical ACKs must survive pair acceptance and restored FIFO replay.
    store.conn.execute(
        "UPDATE cycles SET acked_at=? WHERE state='acked'",
        ((AT + timedelta(minutes=6)).isoformat(),),
    )
    store.set_capture_only(True)
    store.close()


async def verify(store, dsn):
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        return await paired_backup_spool.verify_acked_primary(store, conn)


def acceptance_module():
    spec = importlib.util.spec_from_file_location(
        "paired_acceptance", ROOT / "ops/paired-restore-acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_acked_exact_verification_reads_without_sqlite_mutation(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    store = SpoolStore(path)
    before = store.conn.execute("SELECT * FROM cycles").fetchall()
    meta = store.conn.execute("SELECT * FROM meta").fetchall()
    assert asyncio.run(verify(store, database("collector"))) == {
        "acked_cycles": 2,
        "acked_observations": 2,
    }
    assert store.conn.execute("SELECT * FROM cycles").fetchall() == before
    assert store.conn.execute("SELECT * FROM meta").fetchall() == meta
    store.close()


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "http_status",
        "duration_ms",
        "body_sha256",
        "rows_written",
        "error",
        "wait_time_seconds",
        "wait_time_status",
        "vehicles_in_queue",
        "is_paused",
        "extra_observation",
    ],
)
def test_invalid_acked_fails_before_recovery_or_replay(database, tmp_path, damage):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    with psycopg.connect(database("admin")) as conn:
        if damage == "missing":
            conn.execute("DELETE FROM collector_runs WHERE time=%s", (AT,))
        elif damage == "extra_observation":
            conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES (8,'Extra',1)")
            conn.execute(
                "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
                "vehicles_in_queue,is_paused) VALUES (%s,8,0,0,false)",
                (AT,),
            )
        else:
            table = (
                "collector_runs"
                if damage in {"http_status", "duration_ms", "body_sha256", "rows_written", "error"}
                else "observations"
            )
            value = {
                "http_status": 500,
                "duration_ms": 123,
                "body_sha256": "f" * 64,
                "rows_written": 0,
                "error": "different",
                "wait_time_seconds": 999,
                "wait_time_status": "missing",
                "vehicles_in_queue": 99,
                "is_paused": True,
            }[damage]
            conn.execute(
                psycopg.sql.SQL("UPDATE {} SET {}=%s WHERE time=%s").format(
                    psycopg.sql.Identifier(table), psycopg.sql.Identifier(damage)
                ),
                (value, AT),
            )
    store = SpoolStore(path)
    before = store.conn.execute("SELECT * FROM cycles").fetchall()
    with pytest.raises(ReplayConflict):
        asyncio.run(acceptance_module().recover_pair(store, database("collector")))
    assert store.conn.execute("SELECT * FROM cycles").fetchall() == before
    assert store.capture_only()
    with psycopg.connect(database("collector")) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM collector_runs WHERE time>%s", (AT + timedelta(minutes=1),)
            ).fetchone()[0]
            == 0
        )
    store.close()


def test_mixed_pair_recovers_fifo_once_without_mutating_source(database, tmp_path):
    source = tmp_path / "source/spool.sqlite3"
    asyncio.run(mixed_fixture(source, database("collector")))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    owned = tmp_path / "owned/spool.sqlite3"
    owned.parent.mkdir()
    owned.write_bytes(source.read_bytes())
    store = SpoolStore(owned)
    before = store.conn.execute("SELECT * FROM cycles WHERE state='acked' ORDER BY seq").fetchall()
    evidence = asyncio.run(acceptance_module().recover_pair(store, database("collector")))
    assert evidence["replayed_sequences"] == [3, 4, 5, 6]
    assert evidence["acked_cycles"] == 2
    assert evidence["recovered_started"] == 1
    assert evidence["verified_cycles"] == 6
    assert store.conn.execute("SELECT * FROM cycles WHERE seq<=2 ORDER BY seq").fetchall() == before
    assert store.status().pending_count == 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0] == 6
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 5
        assert conn.execute(
            "SELECT error,rows_written FROM collector_runs WHERE time=%s",
            (AT + timedelta(minutes=5),),
        ).fetchone() == ("interrupted_before_durable_result", 0)
        assert conn.execute(
            "SELECT wait_time_seconds,vehicles_in_queue,is_paused FROM observations ORDER BY time"
        ).fetchall() == [
            (0, 1, False),
            (60, 2, True),
            (120, 3, False),
            (180, 4, False),
            (240, 5, False),
        ]
    with psycopg.connect(database("admin")) as conn:
        for table in ("alerts", "eta_alerts", "surge_alerts"):
            assert (
                conn.execute(
                    psycopg.sql.SQL("SELECT count(*) FROM {}").format(psycopg.sql.Identifier(table))
                ).fetchone()[0]
                == 0
            )
    store.close()


def test_committed_pending_retry_is_idempotent(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    store = SpoolStore(path)
    store.set_capture_only(False)

    async def commit():
        async with AsyncConnectionPool(
            database("collector"), open=False, kwargs={"row_factory": dict_row}
        ) as pool:
            await replay_once(store, pool, AT + timedelta(minutes=10))

    asyncio.run(commit())
    # Reconstruct only the crash-before-ACK state; PostgreSQL is already committed.
    store.conn.execute("UPDATE cycles SET state='pending',acked_at=NULL WHERE seq=3")
    store.set_capture_only(True)
    evidence = asyncio.run(acceptance_module().recover_pair(store, database("collector")))
    assert evidence["replayed_sequences"] == [3, 4, 5, 6]
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0] == 6
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 5
    store.close()


def test_conflicting_pending_is_retained(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    with psycopg.connect(database("collector")) as conn:
        conn.execute(
            "INSERT INTO collector_runs(time,duration_ms,rows_written,error) "
            "VALUES (%s,0,0,'conflict')",
            (AT + timedelta(minutes=2),),
        )
    store = SpoolStore(path)
    payload = store.conn.execute("SELECT payload,payload_sha256 FROM cycles WHERE seq=3").fetchone()
    with pytest.raises(ReplayConflict):
        asyncio.run(acceptance_module().recover_pair(store, database("collector")))
    assert store.next_pending().seq == 3
    assert (
        store.conn.execute("SELECT payload,payload_sha256 FROM cycles WHERE seq=3").fetchone()
        == payload
    )
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute("SELECT count(*) FROM collector_runs").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 2
    store.close()


def test_native_replay_still_prunes_by_default(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    store = SpoolStore(path)
    store.set_capture_only(False)

    async def replay():
        async with AsyncConnectionPool(
            database("collector"), open=False, kwargs={"row_factory": dict_row}
        ) as pool:
            await replay_once(store, pool, datetime.now(UTC))

    asyncio.run(replay())
    assert store.conn.execute("SELECT seq FROM cycles ORDER BY seq").fetchall() == [
        (3,),
        (4,),
        (5,),
        (6,),
    ]
    store.close()


def package_pair(spool, directory, sql=b"SELECT 1;", runtime=None):
    """Test utility: real bytes plus explicit synthetic provenance unless supplied."""
    acceptance_module()
    from paired_backup_manifest import build_manifest

    directory.mkdir(mode=0o700)
    artifacts = {}
    stamp = "20261013-090000"
    for kind, suffix, raw in [
        ("sql", ".sql.gz", sql),
        ("spool", ".spool.sqlite3.gz", spool.read_bytes()),
    ]:
        name = f"avelren-{stamp}{suffix}"
        data = gzip.compress(raw)
        digest = hashlib.sha256(data).hexdigest()
        (directory / name).write_bytes(data)
        (directory / (name + ".sha256")).write_text(f"{digest}  {name}\n")
        artifacts[kind] = {"name": name, "sha256": digest, "bytes": len(data)}
    now = datetime.now(UTC).isoformat()
    manifest = build_manifest(
        stamp,
        artifacts,
        {key: {"started_at": now, "finished_at": now} for key in ("sql", "spool")},
        runtime
        or {
            "source_commit": "a" * 40,
            "image_id": "sha256:" + "b" * 64,
            "container_id": "c" * 64,
            "restart_count": 0,
            "started_at": now,
        },
        paired_backup_spool.inspect_spool(spool),
        True,
    )
    name = f"avelren-{stamp}.pair.json"
    (directory / name).write_text(json.dumps(manifest))
    return name


def test_reader_validates_real_schema_and_preserves_inputs(database, tmp_path):
    spool = tmp_path / "source/spool.sqlite3"
    asyncio.run(mixed_fixture(spool, database("collector")))
    directory = tmp_path / "pair"
    name = package_pair(spool, directory)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    acceptance_module().read_pair(directory, name, tmp_path / "owned")
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert (tmp_path / "owned/restored.sqlite3").read_bytes() == spool.read_bytes()


def test_reader_rejects_mismatched_static_spool_summary(database, tmp_path):
    acceptance_module()
    from paired_backup_manifest import ManifestError

    spool = tmp_path / "source/spool.sqlite3"
    asyncio.run(mixed_fixture(spool, database("collector")))
    directory = tmp_path / "pair"
    name = package_pair(spool, directory)
    manifest = json.loads((directory / name).read_bytes())
    manifest["spool"]["state_counts"].update(acked=1, pending=4)
    (directory / name).write_text(json.dumps(manifest))
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ManifestError, match="spool_summary_invalid"):
        acceptance_module().read_pair(directory, name, tmp_path / "owned")
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert not (tmp_path / "owned").exists()


def legacy_manifest(path, tmp_path):
    directory = tmp_path / "legacy-pair"
    name = package_pair(path, directory, runtime={
        "source_commit": "a4a16b64147fcf28c6245f2032a61279ca7c74ec",
        "image_id": "sha256:e7b02f58581d312ecabc84e9a32389fcfea9d7b2330b0155752fb0c42ca5e4c3",
        "container_id": "c" * 64,
        "restart_count": 0,
        "started_at": (AT - timedelta(days=1)).isoformat(),
    })
    return json.loads((directory / name).read_bytes())


def legacy_fixture(path, database):
    asyncio.run(mixed_fixture(path, database("collector")))
    # Reproduce old INSERT after migration 015: its omitted status gets the default.
    with psycopg.connect(database("admin")) as conn:
        conn.execute("UPDATE observations SET wait_time_status=DEFAULT")


def test_exact_legacy_pair_preserves_acks_and_replays_pending_modern(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    legacy_fixture(path, database)
    manifest = legacy_manifest(path, tmp_path)
    store = SpoolStore(path)
    before = store.conn.execute("SELECT * FROM cycles WHERE state='acked'").fetchall()
    evidence = asyncio.run(acceptance_module().recover_pair(
        store, database("collector"), manifest=manifest,
    ))
    assert evidence["acked_cycles"] == 2
    assert evidence["replayed_sequences"] == [3, 4, 5, 6]
    assert store.conn.execute("SELECT * FROM cycles WHERE seq<=2").fetchall() == before
    with psycopg.connect(database("collector")) as conn:
        assert conn.execute(
            "SELECT wait_time_status FROM observations ORDER BY time"
        ).fetchall() == [("legacy_unknown",), ("legacy_unknown",),
                         ("reported",), ("reported",), ("reported",)]
    store.close()


@pytest.mark.parametrize("damage", [
    "source_commit", "image_id", "status_null", "status_reported", "status_missing",
    "wait_time_seconds", "vehicles_in_queue", "is_paused", "duration_ms", "http_status",
    "body_sha256", "rows_written", "error", "missing_run",
    "missing_observation", "extra_observation",
])
def test_legacy_exception_rejects_unknown_runtime_and_corruption(database, tmp_path, damage):
    path = tmp_path / "spool.sqlite3"
    legacy_fixture(path, database)
    manifest = legacy_manifest(path, tmp_path)
    if damage in {"source_commit", "image_id"}:
        manifest["runtime"][damage] = (
            "d" * 40 if damage == "source_commit" else "sha256:" + "d" * 64
        )
    else:
        with psycopg.connect(database("admin")) as conn:
            if damage == "missing_run":
                conn.execute("DELETE FROM collector_runs WHERE time=%s", (AT,))
            elif damage == "missing_observation":
                conn.execute("DELETE FROM observations WHERE time=%s", (AT,))
            elif damage == "extra_observation":
                conn.execute(
                    "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(8,'Extra',1)"
                )
                conn.execute("INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
                             "vehicles_in_queue,is_paused) VALUES(%s,8,0,0,false)", (AT,))
            else:
                field = "wait_time_status" if damage.startswith("status_") else damage
                value = {"status_null": None, "status_reported": "reported",
                         "status_missing": "missing", "wait_time_seconds": 999,
                         "vehicles_in_queue": 99, "is_paused": True, "duration_ms": 999,
                         "http_status": 500, "body_sha256": "f" * 64, "rows_written": 0,
                         "error": "corrupted"}[damage]
                table = "collector_runs" if damage in {
                    "duration_ms", "http_status", "body_sha256", "rows_written", "error"
                } else "observations"
                conn.execute(psycopg.sql.SQL("UPDATE {} SET {}=%s WHERE time=%s").format(
                    psycopg.sql.Identifier(table), psycopg.sql.Identifier(field)), (value, AT))
    store = SpoolStore(path)
    before = store.conn.execute("SELECT * FROM cycles").fetchall()
    with pytest.raises(ReplayConflict):
        asyncio.run(acceptance_module().recover_pair(
            store, database("collector"), manifest=manifest,
        ))
    assert store.conn.execute("SELECT * FROM cycles").fetchall() == before
    assert store.capture_only()
    store.close()


def test_unknown_runtime_keeps_modern_strict_recovery(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    asyncio.run(mixed_fixture(path, database("collector")))
    manifest = legacy_manifest(path, tmp_path)
    manifest["runtime"]["source_commit"] = "d" * 40
    store = SpoolStore(path)
    try:
        evidence = asyncio.run(acceptance_module().recover_pair(
            store, database("collector"), manifest=manifest,
        ))
        assert evidence["verified_cycles"] == 6
    finally:
        store.close()


def test_legacy_committed_pending_is_not_granted_ack_exception(database, tmp_path):
    path = tmp_path / "spool.sqlite3"
    legacy_fixture(path, database)
    manifest = legacy_manifest(path, tmp_path)
    store = SpoolStore(path)
    store.conn.execute("UPDATE cycles SET state='pending',acked_at=NULL WHERE seq=2")
    payload = store.conn.execute("SELECT payload,payload_sha256 FROM cycles WHERE seq=2").fetchone()
    with pytest.raises(ReplayConflict):
        asyncio.run(acceptance_module().recover_pair(
            store, database("collector"), manifest=manifest,
        ))
    assert store.next_pending().seq == 2
    assert store.conn.execute(
        "SELECT payload,payload_sha256 FROM cycles WHERE seq=2"
    ).fetchone() == payload
    store.close()


@pytest.mark.parametrize("unsafe", [False, True])
def test_legacy_role_placeholder_is_restricted_or_refuses_existing_role(database, unsafe):
    script = (ROOT / "ops/paired-restore-legacy-role.sql").read_text()
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        try:
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute(script)
            assert conn.execute("SELECT 1 FROM pg_roles WHERE rolname='avelren'").fetchone() is None
            conn.execute("SET avelren.paired_rehearsal='1'")
            if unsafe:
                conn.execute("CREATE ROLE avelren LOGIN")
                with pytest.raises(psycopg.errors.RaiseException):
                    conn.execute(script)
                assert conn.execute(
                    "SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren'"
                ).fetchone() == (True,)
            else:
                conn.execute(script)
                conn.execute(script)
                assert conn.execute(
                    "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
                    "rolbypassrls FROM pg_roles WHERE rolname='avelren'"
                ).fetchone() == (False, False, False, False, False, False)
                assert conn.execute(
                    "SELECT count(*) FROM pg_auth_members WHERE member='avelren'::regrole "
                    "OR roleid='avelren'::regrole"
                ).fetchone() == (0,)
        finally:
            conn.execute("DROP ROLE IF EXISTS avelren")
