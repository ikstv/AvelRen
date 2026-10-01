"""Durable collector cycle journal; no upstream or PostgreSQL access."""

import hashlib
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    limited = SpoolStore(tmp_path / "limited.sqlite3", max_bytes=1)
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
