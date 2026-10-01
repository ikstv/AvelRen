"""Replay control flow with a real SQLite spool and no upstream transport."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from avelren import collector_replay
from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult

AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class Pool:
    @asynccontextmanager
    async def connection(self):
        yield object()


def _pending(tmp_path: Path, at: datetime = AT, error: str | None = None):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    seq = store.begin(at)
    store.finish(seq, FetchResult(None, 429 if error else 200, 4, None, error), 1)
    return store, seq


def _patch_db(monkeypatch):
    calls = {}
    for name in (
        "upsert_countries", "upsert_checkpoints", "insert_observations", "record_run",
        "verify_committed_cycle", "record_derived", "_derived_processed",
        "_cycle_exists",
    ):
        result = 0 if name == "insert_observations" else None
        if name == "_derived_processed":
            result = False
        if name == "_cycle_exists":
            result = False
        calls[name] = AsyncMock(return_value=result)
        monkeypatch.setattr(collector_replay, name, calls[name], raising=False)
    for obj in (collector_replay.alerts, collector_replay.eta):
        monkeypatch.setattr(obj, "evaluate", AsyncMock())
        expire = "expire_stale" if obj is collector_replay.alerts else "expire_passed"
        monkeypatch.setattr(obj, expire, AsyncMock())
    return calls


def test_replay_commits_fifo(tmp_path, monkeypatch):
    store, first = _pending(tmp_path)
    second = store.begin(AT + timedelta(minutes=1))
    store.finish(second, FetchResult(None, 429, 3, None, "HTTP 429"), 1)
    calls = _patch_db(monkeypatch)
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT + timedelta(minutes=3)))
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT + timedelta(minutes=3)))
    assert store.next_pending() is None
    expected_times = [AT, AT + timedelta(minutes=1)]
    assert [c.args[1] for c in calls["record_run"].await_args_list] == expected_times
    assert [first, second] == [1, 2]


def test_db_outage_retains_pending(tmp_path, monkeypatch):
    store, seq = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    calls["record_run"].side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    assert store.next_pending().seq == seq


def test_commit_before_ack_is_idempotent(tmp_path, monkeypatch):
    store, seq = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    real_ack = store.ack
    attempts = 0

    def crash_once(value):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("crash after commit")
        real_ack(value)

    monkeypatch.setattr(store, "ack", crash_once)
    with pytest.raises(RuntimeError, match="crash after commit"):
        asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    assert store.next_pending().seq == seq
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    assert calls["verify_committed_cycle"].await_count == 2
    assert store.next_pending() is None


def test_time_collision_retains_pending(tmp_path, monkeypatch):
    store, seq = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    calls["verify_committed_cycle"].side_effect = collector_replay.ReplayConflict("different")
    with pytest.raises(collector_replay.ReplayConflict):
        asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    assert store.next_pending().seq == seq


def test_existing_timestamp_conflict_has_no_primary_mutation(tmp_path, monkeypatch):
    store, seq = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    calls["_cycle_exists"].return_value = True
    calls["verify_committed_cycle"].side_effect = collector_replay.ReplayConflict("different")
    with pytest.raises(collector_replay.ReplayConflict):
        asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    calls["record_run"].assert_not_awaited()
    calls["insert_observations"].assert_not_awaited()
    assert store.next_pending().seq == seq


def test_interrupted_cycle_records_error_only(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    store.begin(AT)
    store.recover_started()
    calls = _patch_db(monkeypatch)
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT))
    assert calls["record_run"].await_args.args[-1] == "interrupted_before_durable_result"
    calls["insert_observations"].assert_not_awaited()


def test_old_cycle_skips_push(tmp_path, monkeypatch):
    store, _ = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT + timedelta(seconds=121)))
    assert "delayed_replay" in calls["record_derived"].await_args.kwargs["error"]
    collector_replay.alerts.evaluate.assert_not_awaited()
    collector_replay.eta.evaluate.assert_not_awaited()


def test_fresh_cycle_runs_derived(tmp_path, monkeypatch):
    store, _ = _pending(tmp_path)
    calls = _patch_db(monkeypatch)
    assert asyncio.run(collector_replay.replay_once(store, Pool(), AT + timedelta(seconds=120)))
    assert calls["record_derived"].await_args.kwargs["error"] is None


def test_runtime_prunes_acked_after_24_hours(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    now = datetime.now(UTC)
    old_at = now - timedelta(hours=25)
    old = store.begin(old_at)
    store.finish(old, FetchResult(None, 429, 4, None, "HTTP 429"), 1)
    store.ack(old)
    store.conn.execute("UPDATE cycles SET acked_at=? WHERE seq=?", (old_at.isoformat(), old))
    seq = store.begin(now)
    store.finish(seq, FetchResult(None, 429, 4, None, "HTTP 429"), 1)
    _patch_db(monkeypatch)
    assert asyncio.run(collector_replay.replay_once(store, Pool(), now))
    assert store.status().acked_count == 1  # Only the just-acknowledged cycle remains.


def test_slow_db_crossing_120_seconds_skips_derived(tmp_path, monkeypatch):
    store, _ = _pending(tmp_path)
    calls = _patch_db(monkeypatch)

    class SlowPool:
        entered = 0

        @asynccontextmanager
        async def connection(self):
            self.entered += 1
            if self.entered == 1:
                await asyncio.sleep(0.8)
            yield object()

    just_fresh = AT + timedelta(seconds=119.5)
    assert asyncio.run(collector_replay.replay_once(store, SlowPool(), just_fresh))
    assert "delayed_replay" in calls["record_derived"].await_args.kwargs["error"]
