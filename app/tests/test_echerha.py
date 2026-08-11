import asyncio
from datetime import timedelta

import httpx
import pytest

from avelren import echerha
from avelren.config import Settings
from avelren.models import WorkloadResponse

DEVICE_ID = "123e4567-e89b-12d3-a456-426614174000"


def _v5_payload() -> dict[str, object]:
    return {
        "data": [
            {
                "id": 101,
                "title": "Synthetic checkpoint",
                "country_id": 7,
                "for_vehicle_type": 1,
                "queue_flow": 4,
                "is_paused": False,
                "cancel_after": None,
                "lat": 49.0,
                "lng": 24.0,
                "wait_time": 15,
                "vehicle_in_active_queues_counts": 3,
                "tooltip": "Synthetic tooltip",
                "harmless_extra": "ignored",
            }
        ],
        "filters": {
            "countries": [
                {
                    "id": 7,
                    "name": "Synthetic country",
                    "icon": None,
                    "harmless_extra": "ignored",
                }
            ]
        },
        "harmless_extra": "ignored",
    }


def _v5_response() -> httpx.Response:
    response = httpx.Response(200, json=_v5_payload())
    response._elapsed = timedelta(0)
    return response


def _configure(monkeypatch: pytest.MonkeyPatch, *, device_id: str = DEVICE_ID) -> None:
    values = {
        "echerha_api_version": 5,
        "echerha_client_version": "3.9.0",
        "echerha_device_id": device_id,
        "echerha_device_name": "AvelRen collector",
    }
    for name, value in values.items():
        monkeypatch.setitem(echerha.settings.__dict__, name, value)


def test_workload_url_uses_v5_vehicle_endpoint() -> None:
    configured = Settings(
        _env_file=None,
        echerha_base_url="https://source.example/api",
        echerha_vehicle_type=1,
    )

    assert configured.workload_url == "https://source.example/api/v5/workload/1"


def test_request_uses_current_guest_protocol_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _v5_response()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await echerha.fetch_workload(client)
        assert result.error is None

    asyncio.run(exercise())

    assert requests[0].headers["X-User-Agent"] == "UABorder/3.9.0 Web/1.1.0 User/guest"


def test_request_uses_official_guest_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _v5_response()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await echerha.fetch_workload(client)
        assert result.error is None

    asyncio.run(exercise())

    headers = requests[0].headers
    assert headers["Accept"] == "application/json"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Client-Locale"] == "uk"
    assert headers["X-Device-Id"] == DEVICE_ID
    assert headers["X-Device-Name"] == "AvelRen collector"
    assert headers["User-Agent"].startswith("AvelRen/")
    assert "Authorization" not in headers
    assert "Cookie" not in headers


def test_client_defaults_cannot_add_auth_or_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _v5_response()

    async def exercise() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer synthetic"},
            cookies={"session": "synthetic"},
        ) as client:
            result = await echerha.fetch_workload(client)
        assert result.error is None

    asyncio.run(exercise())

    assert "Authorization" not in requests[0].headers
    assert "Cookie" not in requests[0].headers


def test_response_cookie_is_not_reused_next_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = _v5_response()
        if len(requests) == 1:
            response.headers["Set-Cookie"] = "upstream_session=synthetic; Path=/"
        return response

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await echerha.fetch_workload(client)
            second = await echerha.fetch_workload(client)
        assert first.error is None
        assert second.error is None

    asyncio.run(exercise())

    assert len(requests) == 2
    assert all("Cookie" not in request.headers for request in requests)


@pytest.mark.parametrize("device_id", ["", "not-a-uuid"])
def test_invalid_device_id_fails_before_network(
    monkeypatch: pytest.MonkeyPatch, device_id: str
) -> None:
    _configure(monkeypatch, device_id=device_id)
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return _v5_response()

    async def exercise() -> echerha.FetchResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await echerha.fetch_workload(client)

    result = asyncio.run(exercise())

    assert request_count == 0
    assert result.response is None
    assert result.http_status is None
    assert result.error is not None
    assert result.error.startswith("configuration:")


def test_device_id_is_stable_across_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    observed_device_ids: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_device_ids.append(request.headers.get("X-Device-Id"))
        return _v5_response()

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = await echerha.fetch_workload(client)
            second = await echerha.fetch_workload(client)
        assert first.error is None
        assert second.error is None

    asyncio.run(exercise())

    assert observed_device_ids == [DEVICE_ID, DEVICE_ID]


def test_non_200_response_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        response = httpx.Response(422, json={"message": "synthetic rejection"})
        response._elapsed = timedelta(0)
        return response

    async def exercise() -> echerha.FetchResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await echerha.fetch_workload(client)

    result = asyncio.run(exercise())

    assert request_count == 1
    assert result.http_status == 422
    assert result.error == "HTTP 422"


def test_verified_v5_shape_is_compatible_with_current_model() -> None:
    parsed = WorkloadResponse.model_validate(_v5_payload())

    assert len(parsed.data) == 1
    assert parsed.data[0].for_vehicle_type == 1
    assert parsed.data[0].vehicles_in_queue == 3
