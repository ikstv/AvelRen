"""Collector keeps the 60-second source contract without a live DB/HTTP client."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from avelren import collector, echerha
from avelren.collector_replay import ReplayConflict
from avelren.collector_spool import SpoolStore
from avelren.config import Settings
from avelren.echerha import FetchResult


def test_poll_loop_paces_actual_sends_after_preparation(tmp_path, monkeypatch):
    """A slow first preparation must not make the next HTTP attempt arrive early."""
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    clock = SimpleNamespace(value=0.0)
    starts = []
    begun = []
    original_begin = store.begin

    def begin(at):
        begun.append(clock.value)
        seq = original_begin(at)
        clock.value += 15 if len(begun) == 1 else 0
        return seq

    async def sleep(delay):
        clock.value += delay

    async def wait_for(coro, timeout):
        coro.close()
        clock.value += timeout
        raise TimeoutError

    class Stop:
        def is_set(self):
            return len(starts) >= 3

        async def wait(self):
            pass

    async def handler(request):
        starts.append(clock.value)
        return httpx.Response(503, request=request)

    monkeypatch.setattr(store, "begin", begin)
    monkeypatch.setattr(echerha, "settings", Settings(
        _env_file=None, echerha_device_id="11111111-1111-4111-8111-111111111111",
    ))
    monkeypatch.setattr(collector.asyncio, "wait_for", wait_for)
    original_pacer = echerha.RequestPacer
    monkeypatch.setattr(collector, "RequestPacer", lambda **kwargs: original_pacer(
        **kwargs, sleep=sleep,
    ))

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await collector.poll_loop(client, store, Stop(), clock=lambda: clock.value)

    asyncio.run(scenario())
    assert begun == [60.0, 120.0, 180.0]
    assert starts == [75.0, 135.0, 195.0]
    assert store.status().pending_count == 3
    store.close()


def test_one_fetch_per_cycle_when_db_down(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    fetch = AsyncMock(return_value=FetchResult(None, 429, 7, None, "HTTP 429"))
    monkeypatch.setattr(collector, "fetch_workload", fetch)
    asyncio.run(collector.run_cycle(object(), store))
    fetch.assert_awaited_once()
    assert store.next_pending().error == "HTTP 429"


def test_startup_without_db_still_captures(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    result = FetchResult(None, None, 0, None, "timeout")
    monkeypatch.setattr(
        collector, "fetch_workload", AsyncMock(return_value=result)
    )
    monkeypatch.setattr(
        collector, "_new_writer_pool", lambda: (_ for _ in ()).throw(RuntimeError("DB down"))
    )
    async def scenario():
        stop = asyncio.Event()
        writer = asyncio.create_task(collector.writer_supervisor(store, stop))
        await asyncio.sleep(0)
        await collector.run_cycle(object(), store)
        stop.set()
        await writer

    asyncio.run(scenario())
    assert store.status().pending_count == 1


def test_start_times_remain_60_seconds_apart(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    times = []
    pacers = []
    clock = SimpleNamespace(value=0.0)

    async def fetch(_, **kwargs):
        times.append(clock.value)
        pacers.append(kwargs["pacer"])
        clock.value += 5.0
        return FetchResult(None, 429, 4, None, "HTTP 429")

    async def wait_for(coro, timeout):
        coro.close()
        clock.value += timeout
        raise TimeoutError

    monkeypatch.setattr(collector, "fetch_workload", fetch)
    monkeypatch.setattr(collector.asyncio, "wait_for", wait_for)

    class Stop:
        def is_set(self):
            return len(times) >= 3

        async def wait(self):
            return None

    asyncio.run(collector.poll_loop(object(), store, Stop(), clock=lambda: clock.value))
    assert times == [60.0, 120.0, 180.0]
    assert pacers[0] is not None
    assert all(pacer is pacers[0] for pacer in pacers)


def test_capture_only_survives_restart(tmp_path):
    path = tmp_path / "cycles.sqlite3"
    store = SpoolStore(path)
    store.set_capture_only(True)
    store.close()
    assert SpoolStore(path).capture_only() is True


def test_control_acks_only_after_pool_close(tmp_path):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    store.set_capture_only(True)
    events = []

    class Pool:
        async def close(self):
            events.append("closed")

    async def writer():
        await asyncio.Event().wait()

    async def scenario():
        task = asyncio.create_task(writer())
        await asyncio.sleep(0)
        await collector.stop_writer(Pool(), task, store)

    original = store.set_mode_ack

    def acknowledge(enabled):
        events.append("ack")
        original(enabled)

    store.set_mode_ack = acknowledge
    asyncio.run(scenario())
    assert events == ["closed", "ack"]
    assert store.status().mode_ack is True


def test_run_cycle_records_utc_start_before_fetch(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    started = []
    original = store.begin

    def begin(at):
        started.append(at)
        return original(at)

    store.begin = begin
    result = FetchResult(None, 429, 1, None, "HTTP 429")
    monkeypatch.setattr(collector, "fetch_workload", AsyncMock(return_value=result))
    asyncio.run(collector.run_cycle(object(), store))
    assert len(started) == 1
    assert started[0].tzinfo == UTC
    assert isinstance(started[0], datetime)


def test_replay_conflict_blocks_writer_restarts(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    opened = []

    class Pool:
        async def open(self, **kwargs):
            opened.append(1)

        async def close(self):
            pass

    async def conflict(*args):
        raise ReplayConflict("different cycle")

    monkeypatch.setattr(collector, "_new_writer_pool", Pool)
    monkeypatch.setattr(collector, "assert_schema_at_least", AsyncMock())
    monkeypatch.setattr(collector, "replay_loop", conflict)

    async def scenario():
        stop = asyncio.Event()
        supervisor = asyncio.create_task(collector.writer_supervisor(store, stop))
        await asyncio.sleep(0.8)
        stop.set()
        await supervisor

    asyncio.run(scenario())
    assert len(opened) == 1
    assert store.status().last_error == "ReplayConflict"


def test_late_wakeup_never_shortens_next_interval(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    clock = SimpleNamespace(value=0.0)
    starts = []
    waits = []

    async def fetch(_, **kwargs):
        starts.append(clock.value)
        return FetchResult(None, 503, 1, None, "HTTP 503")

    async def wait_for(coro, timeout):
        coro.close()
        waits.append(timeout)
        clock.value += timeout + (5 if len(waits) == 2 else 0)
        raise TimeoutError

    class Stop:
        def is_set(self):
            return len(starts) >= 3

        async def wait(self):
            pass

    monkeypatch.setattr(collector, "fetch_workload", fetch)
    monkeypatch.setattr(collector.asyncio, "wait_for", wait_for)
    asyncio.run(collector.poll_loop(object(), store, Stop(), clock=lambda: clock.value))
    assert starts == [60.0, 125.0, 185.0]
    assert store.status().pending_count == 3


def test_stop_during_startup_makes_no_source_request(tmp_path, monkeypatch):
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    fetch = AsyncMock(return_value=FetchResult(None, 503, 1, None, "HTTP 503"))
    monkeypatch.setattr(collector, "fetch_workload", fetch)

    async def scenario():
        stop = asyncio.Event()

        async def wait_for(coro, timeout):
            stop.set()
            await coro

        monkeypatch.setattr(collector.asyncio, "wait_for", wait_for)
        await collector.poll_loop(object(), store, stop, clock=lambda: 0.0)

    asyncio.run(scenario())
    fetch.assert_not_awaited()
    assert store.status().pending_count == 0
