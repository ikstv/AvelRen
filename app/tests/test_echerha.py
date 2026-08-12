"""Дротовий контракт запиту до єЧерги (гостьовий v5) і fail-closed валідація конфігу.

Production мігрував на public-source контракт v5; canonical main має збігатися
рівно з тим, що довів canary. Кожен тест фіксує один аспект контракту або одну
умову відмови. Жоден тест не робить реального запиту до єЧерги — транспорт
замокано через httpx.MockTransport, як у test_fcm.

Валідація device-id / device-name — **fail-closed**: при некоректному конфігу
цикл не робить запиту взагалі, а повертає FetchResult з error (його побачить
collector_runs і сторож), не відправивши нічого назовні.
"""

import asyncio
from uuid import UUID

import httpx
import pytest

from avelren import echerha
from avelren.config import Settings

# Довільний, але валідний persistent UUID оператора (не nil).
OPERATOR_UUID = "8cf3ce55-0759-4274-a632-65c7a1a42808"


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"echerha_device_id": OPERATOR_UUID}
    values.update(overrides)
    return Settings(_env_file=None, **values)


class _Capture:
    """Збирає реальні вихідні httpx.Request'и і віддає канонічну v5-відповідь."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def transport(self, *, set_cookie: str | None = None) -> httpx.MockTransport:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            headers = {"Set-Cookie": set_cookie} if set_cookie else {}
            return httpx.Response(
                200,
                headers=headers,
                json={"data": [], "filters": {"countries": []}},
                request=request,
            )

        return httpx.MockTransport(handler)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]


def _run_cycles(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    *,
    n: int = 1,
    set_cookie: str | None = None,
    client_headers: dict[str, str] | None = None,
) -> tuple[_Capture, list[echerha.FetchResult]]:
    monkeypatch.setattr(echerha, "settings", settings)
    cap = _Capture()
    results: list[echerha.FetchResult] = []

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=cap.transport(set_cookie=set_cookie),
            headers=client_headers or {},
        ) as client:
            for _ in range(n):
                results.append(await echerha.fetch_workload(client))

    asyncio.run(run())
    return cap, results


# --- Дротовий контракт v5 --------------------------------------------------


def test_requests_v5_workload_url(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, (res,) = _run_cycles(monkeypatch, _settings())
    assert cap.last.url.path == "/api/v5/workload/1"
    assert res.http_status == 200
    assert res.error is None


def test_sends_guest_required_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings())
    h = cap.last.headers
    assert h["accept"] == "application/json"
    assert h["content-type"] == "application/json"
    assert h["x-client-locale"] == "uk"


def test_sends_x_user_agent_with_client_version(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings(echerha_client_version="3.9.0"))
    assert cap.last.headers["x-user-agent"] == "UABorder/3.9.0 Web/1.1.0 User/guest"


def test_sends_canonical_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings())
    assert cap.last.headers["x-device-id"] == OPERATOR_UUID


def test_sends_device_name(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings(echerha_device_name="AvelRen collector"))
    assert cap.last.headers["x-device-name"] == "AvelRen collector"


def test_parses_workload_and_reports_status(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, (res,) = _run_cycles(monkeypatch, _settings())
    assert res.http_status == 200
    assert res.response is not None
    assert res.error is None
    assert res.body_sha256 is not None


def test_source_non_200_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Помилка джерела — не наша аварія: повертаємо як результат, не кидаємо."""
    monkeypatch.setattr(echerha, "settings", _settings())

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance", request=request)

    async def run() -> echerha.FetchResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await echerha.fetch_workload(client)

    res = asyncio.run(run())
    assert res.http_status == 503
    assert res.error == "HTTP 503"
    assert res.response is None


# --- Device ID: fail-closed, без запиту ------------------------------------


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "12345", "8cf3ce55-0759-4274-a632"])
def test_rejects_unparseable_device_id(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    cap, (res,) = _run_cycles(monkeypatch, _settings(echerha_device_id=bad))
    assert cap.requests == []
    assert res.response is None
    assert "ECHERHA_DEVICE_ID" in (res.error or "")


def test_rejects_nil_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nil UUID граматично валідний, але не називає жодного пристрою."""
    cap, (res,) = _run_cycles(
        monkeypatch, _settings(echerha_device_id="00000000-0000-0000-0000-000000000000")
    )
    assert cap.requests == []
    assert "ECHERHA_DEVICE_ID" in (res.error or "")


def test_canonicalizes_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Форма з фігурними дужками й верхнім регістром приймається у canonical вигляді."""
    cap, _ = _run_cycles(
        monkeypatch, _settings(echerha_device_id="{8CF3CE55-0759-4274-A632-65C7A1A42808}")
    )
    assert cap.last.headers["x-device-id"] == OPERATOR_UUID


def test_accepts_non_v4_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Політика: без обмеження версії/варіанта — приймаємо будь-який не-nil UUID."""
    non_v4 = "8cf3ce55-0759-1274-a632-65c7a1a42808"  # version-nibble = 1
    cap, _ = _run_cycles(monkeypatch, _settings(echerha_device_id=non_v4))
    assert cap.last.headers["x-device-id"] == str(UUID(non_v4))


# --- Device Name (Option A): 1–120 printable ASCII, fail-closed ------------


@pytest.mark.parametrize(
    "bad_name",
    [
        "",  # порожнє
        "AvelRen колектор",  # Unicode
        "bad\nname",  # control char (newline)
        "tab\there",  # control char (tab)
        "x" * 121,  # довше за 120
        "\x7f",  # DEL
    ],
)
def test_rejects_invalid_device_name(monkeypatch: pytest.MonkeyPatch, bad_name: str) -> None:
    cap, (res,) = _run_cycles(monkeypatch, _settings(echerha_device_name=bad_name))
    assert cap.requests == []
    assert res.response is None
    assert "ECHERHA_DEVICE_NAME" in (res.error or "")


@pytest.mark.parametrize("ok_name", ["A", "x" * 120, "AvelRen collector"])
def test_accepts_valid_device_name(monkeypatch: pytest.MonkeyPatch, ok_name: str) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings(echerha_device_name=ok_name))
    assert cap.last.headers["x-device-name"] == ok_name


# --- Security: жодного ambient auth / session state ------------------------


def test_never_inherits_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(
        monkeypatch, _settings(), client_headers={"Authorization": "Bearer AMBIENT"}
    )
    assert "authorization" not in cap.last.headers


def test_never_inherits_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    cap, _ = _run_cycles(monkeypatch, _settings(), client_headers={"Cookie": "ambient=1"})
    assert "cookie" not in cap.last.headers


def test_does_not_replay_set_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set-Cookie з попереднього циклу не сміє повернутися наступним запитом."""
    cap, results = _run_cycles(monkeypatch, _settings(), n=2, set_cookie="sess=leaked; Path=/")
    assert len(cap.requests) == 2
    assert "cookie" not in cap.requests[1].headers
    assert all(r.error is None for r in results)
