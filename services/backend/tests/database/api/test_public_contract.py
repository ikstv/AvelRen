"""Публічні дані, ізоляція пристроїв та відмови API."""

from datetime import datetime, timedelta

import pytest


def test_measurements_history_forecast_and_freshness(api_client, checkpoint, conn, monkeypatch):
    conn.execute(
        "INSERT INTO observations VALUES (now()-interval '1 minute', %s, 3600, 80, false), "
        "(now(), %s, 0, 80, false)",
        (checkpoint, checkpoint),
    )
    points = api_client.get("/checkpoints")
    assert points.status_code == 200
    assert points.json()[0]["id"] == checkpoint
    workload = api_client.get("/workload")
    assert workload.status_code == 200
    assert workload.json()[0]["entry_eta"] is None
    assert workload.json()[0]["vehicles_in_queue"] == 80
    raw = api_client.get(f"/history/{checkpoint}?hours=24")
    assert raw.status_code == 200
    assert raw.json()["resolution"] == "raw"
    assert len(raw.json()["points"]) == 2
    hourly = api_client.get(f"/history/{checkpoint}?hours=72")
    assert hourly.status_code == 200
    assert hourly.json()["resolution"] == "hourly"
    assert sum(p["samples"] for p in hourly.json()["points"]) == 1
    assert hourly.json()["points"][0]["avg_wait_seconds"] == 3600
    forecast = api_client.get(f"/forecast/{checkpoint}")
    assert forecast.status_code == 200
    assert forecast.json()["status"] == "collecting"
    assert forecast.json()["points"] == []
    assert api_client.get(f"/forecast/{checkpoint}/quality").status_code == 200

    async def broken_probe(_conn):
        raise RuntimeError("synthetic telemetry failure")

    monkeypatch.setattr("avelren.telemetry.alert_channel", broken_probe)
    health = api_client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["alert_channel"] == "unknown"
    conn.execute("DELETE FROM observations")
    assert api_client.get("/health").json()["status"] == "stale"


def test_measured_eta_is_not_forecast(api_client, checkpoint, conn):
    measured = conn.execute(
        "INSERT INTO observations VALUES (now(), %s, 3600, 80, false) RETURNING time",
        (checkpoint,),
    ).fetchone()["time"]
    response = api_client.get("/workload")
    assert response.status_code == 200
    eta = datetime.fromisoformat(response.json()[0]["entry_eta"].replace("Z", "+00:00"))
    assert eta == measured + timedelta(seconds=3600)


def test_validation_and_missing_checkpoint(api_client):
    for path in ("/history/1?hours=0", "/history/1?hours=2161", "/forecast/1?hours=169"):
        assert api_client.get(path).status_code == 422
    assert api_client.get("/history/1").status_code == 404
    assert api_client.get("/forecast/1").status_code == 404


def test_foreign_device_cannot_delete_subscription(api_client, checkpoint, device, installation):
    created = api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 50},
        headers=device.headers(),
    )
    assert created.status_code == 201
    sub_id = created.json()["id"]
    foreign = installation().headers()
    api_client.delete(f"/subscriptions/{sub_id}", headers=foreign)
    own = api_client.get("/subscriptions", headers=device.headers())
    assert own.status_code == 200
    assert [row["id"] for row in own.json()] == [sub_id]
    assert api_client.get("/admin/telemetry", headers=foreign).status_code == 403
    assert api_client.get("/admin/telemetry").status_code == 401


@pytest.mark.parametrize("failure", ["connection", "pool"])
def test_database_unavailable_returns_retry_after(api_client, monkeypatch, failure):
    from psycopg import AsyncConnection, OperationalError
    from psycopg_pool import PoolTimeout

    async def unavailable(*args, **kwargs):
        raise OperationalError("synthetic outage") if failure == "connection" else PoolTimeout()

    monkeypatch.setattr(AsyncConnection, "execute", unavailable)
    response = api_client.get("/workload")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
