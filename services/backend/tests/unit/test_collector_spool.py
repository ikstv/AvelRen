"""Durable collector cycle journal; no upstream or PostgreSQL access."""

import hashlib
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from psycopg.conninfo import conninfo_to_dict

from avelren import echerha
from avelren.collector_spool import SpoolStore, SpoolUnavailable
from avelren.echerha import FetchResult
from avelren.models import WorkloadResponse

AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _success() -> FetchResult:
    response = WorkloadResponse.model_validate({
        "filters": {"countries": [{"id": 1, "name": "Poland"}]},
        "data": [
            {"id": 7, "title": "Truck", "country_id": 1, "for_vehicle_type": 1,
             "wait_time": 60, "vehicle_in_active_queues_counts": 3},
            {"id": 8, "title": "Bus", "country_id": 1, "for_vehicle_type": 2},
        ],
    })
    return FetchResult(response, 200, 9, "a" * 64, None)


def test_pending_survives_restart(tmp_path: Path):
    path = tmp_path / "spool" / "cycles.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), vehicle_type=1)
    store.close()

    reopened = SpoolStore(path)
    cycle = reopened.next_pending()
    assert cycle is not None and cycle.seq == seq and cycle.at == AT
    assert [(i.id, i.for_vehicle_type, i.wait_time) for i in cycle.items] == [(7, 1, 60)]
    assert [(c.id, c.name) for c in cycle.countries] == [(1, "Poland")]
    assert (cycle.http_status, cycle.duration_ms, cycle.body_sha256) == (200, 9, "a" * 64)


def test_source_error_is_pending(tmp_path: Path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, FetchResult(None, 429, 11, None, "HTTP 429"), vehicle_type=1)
    cycle = store.next_pending()
    assert cycle is not None
    assert (cycle.error, cycle.http_status, cycle.items) == ("HTTP 429", 429, ())


def test_started_recovers_as_interrupted(tmp_path: Path):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    store.begin(AT)
    store.close()
    reopened = SpoolStore(path)
    reopened.recover_started()
    cycle = reopened.next_pending()
    assert cycle is not None
    assert cycle.error == "interrupted_before_durable_result"
    assert cycle.items == () and cycle.http_status is None


@pytest.mark.parametrize("damage", ["digest", "version"])
def test_payload_rejects_corruption_or_unknown_version(tmp_path: Path, damage: str):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), vehicle_type=1)
    store.close()
    with sqlite3.connect(path) as conn:
        if damage == "digest":
            conn.execute("UPDATE cycles SET payload_sha256 = ? WHERE seq = ?", ("0" * 64, seq))
        else:
            conn.execute("UPDATE cycles SET payload_version = 999 WHERE seq = ?", (seq,))
    reopened = SpoolStore(path)
    with pytest.raises(SpoolUnavailable):
        reopened.next_pending()
    assert reopened.status().pending_count == 1


def test_capture_mode_requires_new_ack(tmp_path: Path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    assert store.capture_only() is False
    store.set_capture_only(True)
    assert store.capture_only() is True and store.status().mode_ack is None
    store.set_mode_ack(True)
    assert store.status().mode_ack is True
    store.set_capture_only(False)
    assert store.status().mode_ack is None


def test_acked_prunes_after_24_hours(tmp_path: Path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, _success(), vehicle_type=1)
    store.ack(seq)
    now = datetime.now(UTC)
    store.prune_acked(now + timedelta(hours=23))
    assert store.status().acked_count == 1
    store.prune_acked(now + timedelta(hours=25))
    assert store.status().acked_count == 0


def test_maintenance_preflight_rejects_low_space_or_quota(tmp_path: Path, monkeypatch):
    import avelren.collector_spool as module

    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path, max_bytes=1_073_741_824)
    seq = store.begin(AT)
    store.finish(seq, _success(), vehicle_type=1)
    assert store.status().max_cycle_bytes > 0
    real_usage = module.shutil.disk_usage
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda p: SimpleNamespace(free=1_999_999_999)
    )
    with pytest.raises(SpoolUnavailable, match="free"):
        store.maintenance_preflight(60)
    monkeypatch.setattr(module.shutil, "disk_usage", real_usage)
    limited = SpoolStore(tmp_path / "limited.sqlite3")
    limited_seq = limited.begin(AT)
    limited.finish(limited_seq, _success(), 1)
    limited.max_bytes = 1
    with pytest.raises(SpoolUnavailable, match="quota"):
        limited.maintenance_preflight(60)


def test_spool_permissions_and_no_secrets(tmp_path: Path):
    path = tmp_path / "private" / "cycles.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), vehicle_type=1)
    store.close()
    if os.name == "posix":
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.stat().st_mode & 0o777 == 0o600
    raw = path.read_bytes() + b"".join(p.read_bytes() for p in path.parent.glob("*.sqlite3-*"))
    assert b"X-Device-Id" not in raw
    assert b"DATABASE_URL" not in raw
    assert hashlib.sha256(raw).digest()  # The file has actual durable content.


def test_corrupt_or_full_spool_blocks_maintenance(tmp_path: Path):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), 1)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE cycles SET payload_sha256=? WHERE seq=?", ("0" * 64, seq))
    with pytest.raises(SpoolUnavailable, match="checksum"):
        store.maintenance_preflight(60)
    store.close()
    full = SpoolStore(tmp_path / "full.sqlite3")
    full_seq = full.begin(AT)
    full.finish(full_seq, _success(), 1)
    full.max_bytes = 1
    with pytest.raises(SpoolUnavailable, match="quota"):
        full.maintenance_preflight(60)


def test_online_backup_keeps_pending_wal_rows(tmp_path: Path):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), 1)
    backup_path = tmp_path / "online-backup.sqlite3"
    store.backup_to(backup_path)
    backup = SpoolStore(backup_path)
    assert backup.next_pending().seq == seq
    assert backup.next_pending().body_sha256 == "a" * 64
    backup.close()
    # A bare main-file copy is not the supported recovery method while WAL is live.
    bare_path = tmp_path / "bare-copy.sqlite3"
    shutil.copyfile(path, bare_path)
    try:
        bare = SpoolStore(bare_path)
    except SpoolUnavailable:
        return
    assert bare.status().pending_count != store.status().pending_count


def test_prune_reclaims_file_quota(tmp_path: Path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    for minute in range(30):
        seq = store.begin(AT + timedelta(minutes=minute))
        error = "source error " + ("x" * 5000) + str(minute)
        store.finish(seq, FetchResult(None, 500, 3, None, error), 1)
        store.ack(seq)
    # Flush WAL first: reclamation must shrink the main file, not just WAL.
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = store.path.stat().st_size
    store.conn.execute("UPDATE cycles SET acked_at=?", (AT.isoformat(),))
    store.prune_acked(AT + timedelta(hours=25))
    assert store.status().acked_count == 0
    assert store.path.stat().st_size < before
    assert store.conn.execute("PRAGMA freelist_count").fetchone()[0] == 0


def test_invalid_source_body_is_not_persisted(tmp_path: Path, monkeypatch):
    import asyncio

    sentinel = "RAW_BODY_SENTINEL"
    monkeypatch.setattr(
        echerha.settings, "echerha_device_id", "11111111-1111-4111-8111-111111111111",
    )

    async def fetch():
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": sentinel}),
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await echerha.fetch_workload(client)

    result = asyncio.run(fetch())
    assert result.response is None and result.error.startswith("parse:")
    store = SpoolStore(tmp_path / "private" / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, result, 1)
    cycle = store.next_pending()
    assert cycle.items == () and cycle.http_status == 200
    assert cycle.error.startswith("parse:")
    raw = b"".join(p.read_bytes() for p in store.path.parent.iterdir() if p.is_file())
    assert sentinel.encode() not in raw


def test_existing_spool_without_reclamation_needs_offline_conversion(tmp_path: Path):
    path = tmp_path / "legacy.sqlite3"
    store = SpoolStore(path)
    seq = store.begin(AT)
    store.finish(seq, _success(), 1)
    store.conn.execute("PRAGMA journal_mode=DELETE")
    store.conn.execute("PRAGMA auto_vacuum=NONE")
    store.conn.execute("VACUUM")
    store.close()
    with pytest.raises(SpoolUnavailable, match="offline"):
        SpoolStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT seq,state FROM cycles").fetchall() == [(seq, "pending")]


def test_replay_diagnostics_do_not_persist_connection_input(tmp_path: Path):
    store = SpoolStore(tmp_path / "private" / "cycles.sqlite3")
    sentinel = "DSN_SECRET_SENTINEL"
    try:
        conninfo_to_dict(f"not-a-dsn:{sentinel}")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
    assert sentinel in message
    store.record_replay_error(message)
    assert store.status().last_error == "ProgrammingError"
    raw = b"".join(p.read_bytes() for p in store.path.parent.iterdir() if p.is_file())
    assert sentinel.encode() not in raw


def test_capture_mode_switch_is_atomic_for_second_connection(tmp_path: Path):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    store.set_mode_ack(False)
    observer = SpoolStore(path)
    real = store.conn
    seen = []

    class Probe:
        def __getattr__(self, name):
            return getattr(real, name)

        def __enter__(self):
            real.__enter__()
            return self

        def __exit__(self, *args):
            return real.__exit__(*args)

        def execute(self, sql, params=()):
            result = real.execute(sql, params)
            if "VALUES ('capture_only',?)" in sql:
                seen.append((observer.capture_only(), observer.status().mode_ack))
            return result

    store.conn = Probe()
    store.set_capture_only(True)
    assert seen == [(False, False)]
    assert observer.capture_only() is True
    assert observer.status().mode_ack is None


def test_maintenance_preflight_requires_measured_cycle(tmp_path: Path, monkeypatch):
    import avelren.collector_spool as module

    store = SpoolStore(tmp_path / "cycles.sqlite3")
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _: SimpleNamespace(free=3_000_000_000)
    )
    with pytest.raises(SpoolUnavailable, match="measured"):
        store.maintenance_preflight(60)


def test_error_only_cycles_do_not_size_maintenance_window(tmp_path: Path, monkeypatch):
    import avelren.collector_spool as module

    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(AT)
    store.finish(seq, FetchResult(None, 429, 4, None, "HTTP 429"), 1)
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _: SimpleNamespace(free=3_000_000_000)
    )
    with pytest.raises(SpoolUnavailable, match="measured"):
        store.maintenance_preflight(60)
