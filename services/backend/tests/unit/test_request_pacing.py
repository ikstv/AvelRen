"""Request pacing and diagnostic boundaries; all HTTP uses MockTransport."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from avelren import echerha
from avelren.config import Settings


def configure(monkeypatch):
    monkeypatch.setattr(echerha, "settings", Settings(
        _env_file=None, echerha_device_id="8cf3ce55-0759-4274-a632-65c7a1a42808",
    ))


@pytest.mark.parametrize("failure", [429, 503, "timeout"])
def test_failed_attempt_still_consumes_interval(monkeypatch, failure):
    configure(monkeypatch)
    clock = SimpleNamespace(value=0.0)
    starts = []
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        # Simulate one early wakeup: pacer must check the deadline again.
        clock.value += delay / 2 if len(sleeps) == 1 else delay

    async def handler(request):
        starts.append(clock.value)
        if failure == "timeout":
            raise httpx.ReadTimeout("", request=request)
        return httpx.Response(failure, request=request)

    async def scenario():
        pacer = echerha.RequestPacer(clock=lambda: clock.value, sleep=sleep)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await echerha.fetch_workload(client, pacer=pacer)
            clock.value = 10.0  # Local work between attempts.
            second = await echerha.fetch_workload(client, pacer=pacer)
        assert first.error and second.error

    asyncio.run(scenario())
    assert starts == [0.0, 60.0]
    assert sleeps == [50.0, 25.0]


def test_redirect_cannot_create_second_request(monkeypatch):
    configure(monkeypatch)
    requests = []

    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "/redirected"})
        return httpx.Response(503)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True,
        ) as client:
            return await echerha.fetch_workload(client)

    result = asyncio.run(scenario())
    assert result.http_status == 302
    assert len(requests) == 1


@pytest.mark.parametrize("headers,expected", [
    ({"x-request-id": "a" * 32, "retry-after": "60"},
     " request_id=" + "a" * 32 + " retry_after_seconds=60"),
    ({"x-correlation-id": "8cf3ce55-0759-4274-a632-65c7a1a42808"},
     " correlation_id=8cf3ce55-0759-4274-a632-65c7a1a42808"),
    ({"x-request-id": "private text", "retry-after": "Wed, 21 Oct"}, ""),
    ({"x-request-id": "a" * 1000, "retry-after": "1234567"}, ""),
    ({"retry-after": "-1", "x-correlation-id": "bad\\nvalue"}, ""),
    ([("x-request-id", "a" * 32), ("x-request-id", "b" * 32)], ""),
    ([("retry-after", "60"), ("retry-after", "61")], ""),
])
def test_response_diagnostic_is_bounded(headers, expected):
    assert echerha.response_diagnostic(httpx.Headers(headers)) == expected


def test_error_log_uses_only_allowlisted_diagnostics(monkeypatch, caplog):
    configure(monkeypatch)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(429, headers={
                "x-request-id": "a" * 32,
                "x-correlation-id": "do-not-log-this",
                "retry-after": "60",
                "set-cookie": "private-cookie",
            }),
        )) as client:
            await echerha.fetch_workload(client)

    asyncio.run(scenario())
    assert "request_id=" + "a" * 32 in caplog.text
    assert "retry_after_seconds=60" in caplog.text
    assert "do-not-log-this" not in caplog.text
    assert "private-cookie" not in caplog.text


def test_pacing_wait_is_excluded_from_http_duration(monkeypatch):
    configure(monkeypatch)
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(echerha, "time", SimpleNamespace(monotonic=lambda: clock.value))

    async def sleep(delay):
        clock.value += delay

    async def handler(request):
        clock.value += 0.25
        return httpx.Response(503)

    async def scenario():
        pacer = echerha.RequestPacer(clock=lambda: clock.value, sleep=sleep)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await echerha.fetch_workload(client, pacer=pacer)
            second = await echerha.fetch_workload(client, pacer=pacer)
        assert first.duration_ms == second.duration_ms == 250
        assert clock.value == 60.25

    asyncio.run(scenario())


def test_cancelled_pacing_wait_does_not_send_request(monkeypatch):
    configure(monkeypatch)
    requests = []

    async def sleep(delay):
        raise asyncio.CancelledError

    async def scenario():
        pacer = echerha.RequestPacer(clock=lambda: 0.0, sleep=sleep)
        await pacer.wait()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(503),
        )) as client:
            with pytest.raises(asyncio.CancelledError):
                await echerha.fetch_workload(client, pacer=pacer)
        assert pacer.last_start == 0.0

    asyncio.run(scenario())
    assert requests == []
