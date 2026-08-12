"""#16 інтеграція: bounded resources на реальному застосунку.

Тіло, concurrency-gate на дорогих читаннях і write-rate-limit на життєвому циклі
(ACK / token / DELETE) перевіряються через TestClient проти справжнього app і БД.
"""

import pytest

from avelren import api, ratelimit


@pytest.fixture(autouse=True)
def _clear_rate_hits():
    ratelimit._hits.clear()
    yield
    ratelimit._hits.clear()


# --- Request body bounds ---------------------------------------------------


def test_oversized_request_body_is_rejected(api_client) -> None:  # noqa: ANN001
    huge = b'{"fcm_token":"' + b"x" * 40000 + b'"}'
    r = api_client.post(
        "/devices", content=huge, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


def test_normal_request_body_still_works(api_client) -> None:  # noqa: ANN001
    r = api_client.post("/devices", json={"fcm_token": "t" * 64, "platform": "android"})
    assert r.status_code == 201
    assert "device_secret" in r.json()


# --- Concurrency gate on expensive reads -----------------------------------


@pytest.mark.parametrize("path", ["/history/{cp}", "/forecast/{cp}", "/forecast/{cp}/quality"])
def test_expensive_endpoint_is_concurrency_gated(api_client, checkpoint, monkeypatch, path):  # noqa: ANN001
    # Насичуємо gate до ліміту — наступний виклик має отримати детермінований 503.
    monkeypatch.setattr(api._expensive_gate, "_in_flight", api._expensive_gate.limit)
    r = api_client.get(path.format(cp=checkpoint))
    assert r.status_code == 503


def test_cheap_endpoint_not_blocked_by_expensive_gate(api_client, monkeypatch) -> None:  # noqa: ANN001
    # Навіть при насиченому дорогому gate дешеві health/workload лишаються живими.
    monkeypatch.setattr(api._expensive_gate, "_in_flight", api._expensive_gate.limit)
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/workload").status_code == 200


# --- Write-side rate limit coverage (ACK / token / DELETE) ------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/alerts/1/ack", None),
        ("post", "/eta-alerts/1/ack", None),
        # token PUT має обов'язкове тіло: без нього 422 (валідація) спрацювала б
        # ДО rate_check. Шлемо валідне тіло, щоб дійти до самого ліміту.
        ("put", "/devices/token", {"fcm_token": "t" * 64}),
        ("delete", "/subscriptions/1", None),
        ("delete", "/eta-targets/1", None),
    ],
)
def test_write_endpoint_is_rate_limited(api_client, method, path, body) -> None:  # noqa: ANN001
    limit = ratelimit.LIMITS["write"][0]
    call = getattr(api_client, method)
    last = None
    # rate_check спрацьовує ДО автентифікації, тож без креденшелів перші `limit`
    # відповідей — 401, а наступна — 429.
    for _ in range(limit + 1):
        last = call(path, json=body) if body is not None else call(path)
    assert last.status_code == 429
