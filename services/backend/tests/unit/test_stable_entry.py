import httpx
import pytest

from avelren.echerha import fetch_stable_entry_time


@pytest.fixture(autouse=True)
def valid_echerha_settings(monkeypatch):
    from avelren.config import settings

    monkeypatch.setattr(settings, "echerha_device_id", "12345678-1234-4234-8234-123456789abc")
    monkeypatch.setattr(settings, "echerha_device_name", "AvelRen test")


def page(rows, current, last):
    return {"data": rows, "meta": {"current_page": current, "last_page": last}}


def row(value, icons=()):
    return {"estimated_time": value, "additional": {"icons": list(icons)}}


@pytest.mark.anyio
async def test_selects_last_stable_vehicle_from_tail():
    def handler(request):
        return httpx.Response(200, json=page([
            row("2026-11-03T20:34:00+02:00", [4]),
            row("2026-11-03T20:20:00+02:00"),
        ], 1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_stable_entry_time(client, 17) == "2026-11-03T20:20:00+02:00"


@pytest.mark.anyio
async def test_skips_return_from_extend_and_uses_previous_page():
    pages = {
        1: page([row("2026-11-03T20:34:00+02:00", [4]), row("2026-11-03T20:20:00+02:00", [10])], 1, 2),
        2: page([row("2026-11-03T19:55:00+02:00")], 2, 2),
    }

    def handler(request):
        return httpx.Response(200, json=pages[int(request.url.params["page"])])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_stable_entry_time(client, 17) == "2026-11-03T19:55:00+02:00"


@pytest.mark.anyio
async def test_normalizes_echerha_ukrainian_time():
    def handler(request):
        return httpx.Response(200, json=page([row("03 листопада 20:34")], 1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_stable_entry_time(client, 17)
    assert result is not None
    assert result.endswith("T20:34:00+02:00") or result.endswith("T20:34:00+03:00")


@pytest.mark.anyio
async def test_upstream_failure_returns_missing_time():
    def handler(request):
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_stable_entry_time(client, 17) is None
