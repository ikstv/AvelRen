"""Повні маршрути під роллю API, без джерела й FCM."""

from datetime import UTC, datetime, timedelta

import pytest

from avelren.config import settings


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "surge_enabled", True)


def cap(conn, device):
    conn.execute(
        "UPDATE devices SET notification_capabilities=ARRAY['surge_v1'] WHERE id=%s",
        (device.device_id,),
    )


def event(conn, checkpoint, device, kind="surge_started"):
    now = datetime.now(UTC)
    row = conn.execute(
        (
            "INSERT INTO surge_events(checkpoint_id,kind,started_at,"
            "updated_at,expires_at) VALUES(%s,%s,%s,%s,%s) RETURNING id"
        ),
        (checkpoint, kind, now, now, now + timedelta(minutes=30)),
    ).fetchone()
    alert = conn.execute(
        (
            "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
            "VALUES(%s,%s,now()) RETURNING id"
        ),
        (row["id"], device.device_id),
    ).fetchone()
    return alert["id"]


def test_create_and_refresh_token_persist_capability(api_client, conn):
    r = api_client.post(
        "/devices",
        json={"fcm_token": "synthetic-" + "a" * 32, "notification_capabilities": ["surge_v1"]},
    )
    assert r.status_code == 201
    d = r.json()
    assert conn.execute(
        "SELECT notification_capabilities FROM devices WHERE id=%s", (d["device_id"],)
    ).fetchone()["notification_capabilities"] == ["surge_v1"]
    h = {"X-Device-Id": d["device_id"], "X-Device-Secret": d["device_secret"]}
    r = api_client.put(
        "/devices/token",
        headers=h,
        json={"fcm_token": "synthetic-" + "b" * 32, "notification_capabilities": ["surge_v1"]},
    )
    assert r.status_code == 200
    assert conn.execute(
        "SELECT notification_capabilities FROM devices WHERE id=%s", (d["device_id"],)
    ).fetchone()["notification_capabilities"] == ["surge_v1"]
    assert (
        api_client.put(
            "/devices/token", headers=h, json={"fcm_token": "synthetic-" + "c" * 32}
        ).status_code
        == 200
    )
    assert (
        conn.execute(
            "SELECT notification_capabilities FROM devices WHERE id=%s", (d["device_id"],)
        ).fetchone()["notification_capabilities"]
        == []
    )


def test_multiple_subscriptions_retry_and_unsupported_forecast(
    api_client, conn, checkpoint, device
):
    cap(conn, device)
    for _ in range(2):
        r = api_client.put(
            f"/surge-subscriptions/{checkpoint}",
            headers=device.headers(),
            json={"forecast_enabled": False, "fact_enabled": True},
        )
        assert r.status_code == 200
    assert conn.execute("SELECT count(*) n FROM surge_subscriptions").fetchone()["n"] == 1
    assert len(api_client.get("/surge-subscriptions", headers=device.headers()).json()) == 1
    assert (
        api_client.put(
            f"/surge-subscriptions/{checkpoint}",
            headers=device.headers(),
            json={"forecast_enabled": True, "fact_enabled": True},
        ).status_code
        == 422
    )
    assert (
        api_client.put(
            "/surge-subscriptions/99999999",
            headers=device.headers(),
            json={"forecast_enabled": False, "fact_enabled": True},
        ).status_code
        == 404
    )


def test_requires_installation_and_new_capability(api_client, checkpoint, device):
    body = {"forecast_enabled": False, "fact_enabled": True}
    assert api_client.put(f"/surge-subscriptions/{checkpoint}", json=body).status_code == 401
    assert (
        api_client.put(
            f"/surge-subscriptions/{checkpoint}", headers=device.headers(), json=body
        ).status_code
        == 409
    )


def test_ack_ownership_and_active_alert_reconciliation(
    api_client, conn, checkpoint, device, installation
):
    cap(conn, device)
    alert = event(conn, checkpoint, device)
    other = installation()
    assert api_client.post(f"/surge-alerts/{alert}/ack", headers=other.headers()).status_code == 404
    keys = api_client.get("/active-alerts", headers=device.headers()).json()
    assert keys["surge_started"] == [alert]
    assert keys["surge_forecast"] == []
    for _ in range(2):
        assert (
            api_client.post(f"/surge-alerts/{alert}/ack", headers=device.headers()).status_code
            == 200
        )
    assert api_client.get("/active-alerts", headers=device.headers()).json()["surge_started"] == []
    assert (
        conn.execute("SELECT status FROM surge_alerts WHERE id=%s", (alert,)).fetchone()["status"]
        == "acknowledged"
    )


def test_delete_subscription_atomically_cancels_only_owner(
    api_client, conn, checkpoint, device, installation
):
    cap(conn, device)
    body = {"forecast_enabled": False, "fact_enabled": True}
    assert (
        api_client.put(
            f"/surge-subscriptions/{checkpoint}", headers=device.headers(), json=body
        ).status_code
        == 200
    )
    alert = event(conn, checkpoint, device)
    other = installation()
    assert (
        api_client.delete(f"/surge-subscriptions/{checkpoint}", headers=other.headers()).status_code
        == 200
    )
    assert (
        conn.execute("SELECT status FROM surge_alerts WHERE id=%s", (alert,)).fetchone()["status"]
        == "pending"
    )
    assert (
        api_client.delete(
            f"/surge-subscriptions/{checkpoint}", headers=device.headers()
        ).status_code
        == 200
    )
    assert (
        conn.execute(
            "SELECT alert_id FROM notification_cancels WHERE device_id=%s", (device.device_id,)
        ).fetchone()["alert_id"]
        == alert
    )
    assert api_client.get("/active-alerts", headers=device.headers()).json()["surge_started"] == []


@pytest.mark.parametrize("database", [15], indirect=True)
def test_schema_015_keeps_legacy_api_and_refuses_surge(api_client):
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/surge/checkpoints").status_code == 503
    assert (
        api_client.post("/devices", json={"notification_capabilities": ["surge_v1"]}).status_code
        == 201
    )


def test_feature_disabled_no_table_queries(api_client, monkeypatch):
    monkeypatch.setattr(settings, "surge_enabled", False)
    assert api_client.get("/surge/checkpoints").status_code == 503
    assert api_client.get("/surge/17").status_code == 503


def test_public_status_has_future_window_and_never_fake_zero(api_client, conn):
    now = datetime.now(UTC)
    conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'Chop fixture',1)")
    conn.execute(
        (
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,"
            "vehicles_in_queue,is_paused) VALUES(%s,17,0,100,false)"
        ),
        (now,),
    )
    assert api_client.get("/surge/17").json()["status"] == "unavailable"
    conn.execute(
        (
            "INSERT INTO surge_predictions(checkpoint_id,issued_at,"
            "window_start,window_end,model_version,score) VALUES(17,%s,%s,%s,"
            "'surge_24h_v1',0.99)"
        ),
        (now, now + timedelta(hours=1), now + timedelta(hours=24)),
    )
    conn.execute(
        (
            "INSERT INTO surge_events(checkpoint_id,kind,started_at,"
            "updated_at,expires_at) VALUES(17,'surge_forecast',%s,%s,%s)"
        ),
        (now, now, now + timedelta(minutes=65)),
    )
    r = api_client.get("/surge/17")
    assert r.status_code == 200
    assert r.json()["status"] == "risk"
    assert r.json()["experimental"] is True
    assert r.json()["model_version"] == "surge_24h_v1"
    assert "probability" not in r.json()
    assert "score" not in r.json()


def test_enabled_checkpoints_returns_real_schema_columns(api_client, conn):
    conn.execute(
        "INSERT INTO checkpoints(id,title,for_vehicle_type,country_name) "
        "VALUES(17,'Чоп',1,'Угорщина')"
    )
    response = api_client.get("/surge/checkpoints")
    assert response.status_code == 200
    assert response.json()[0]["checkpoint_id"] == 17
    assert response.json()[0]["forecast_supported"] is True


def test_five_checkpoint_limit_update_and_delete(api_client, conn, device):
    cap(conn, device)
    ids = list(range(900_100_001, 900_100_007))
    for cid in ids:
        conn.execute(
            "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(%s,'synthetic',1)", (cid,)
        )
    body = {"forecast_enabled": False, "fact_enabled": True}
    for cid in ids[:5]:
        assert (
            api_client.put(
                f"/surge-subscriptions/{cid}", headers=device.headers(), json=body
            ).status_code
            == 200
        )
    result = api_client.put(f"/surge-subscriptions/{ids[5]}", headers=device.headers(), json=body)
    assert result.status_code == 409
    assert "5" in result.json()["detail"]
    assert (
        api_client.put(
            f"/surge-subscriptions/{ids[0]}", headers=device.headers(), json=body
        ).status_code
        == 200
    )
    assert (
        api_client.delete(f"/surge-subscriptions/{ids[0]}", headers=device.headers()).status_code
        == 200
    )
    assert (
        api_client.put(
            f"/surge-subscriptions/{ids[5]}", headers=device.headers(), json=body
        ).status_code
        == 200
    )
    assert len(api_client.get("/surge-subscriptions", headers=device.headers()).json()) == 5


def test_concurrent_subscription_requests_cannot_exceed_five(api_client, conn, device):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    cap(conn, device)
    ids = list(range(900_200_001, 900_200_007))
    for cid in ids:
        conn.execute(
            "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(%s,'synthetic',1)", (cid,)
        )
    barrier = Barrier(6)

    def subscribe(cid):
        barrier.wait(timeout=10)
        return api_client.put(
            f"/surge-subscriptions/{cid}",
            headers=device.headers(),
            json={"forecast_enabled": False, "fact_enabled": True},
        ).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(subscribe, ids))
    assert sorted(statuses) == [200, 200, 200, 200, 200, 409]
    assert len(api_client.get("/surge-subscriptions", headers=device.headers()).json()) == 5
