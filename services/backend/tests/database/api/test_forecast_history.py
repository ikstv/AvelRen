"""Прогноз на синтетичній історії через справжні SQL та публічний API."""

from datetime import UTC, datetime, timedelta


def test_history_separates_count_and_wait_samples(api_client, checkpoint, conn):
    """A missing estimate cannot erase a valid vehicle-count sample."""
    hour = (datetime.now(UTC) - timedelta(hours=1)).replace(minute=10, second=0, microsecond=0)
    samples = (
        (0, 10, 0, "reported"),
        (1, 20, 0, "missing"),
        (2, 30, 0, None),
        (3, 40, 3600, None),
    )
    for minute, vehicles, seconds, status in samples:
        conn.execute(
            "INSERT INTO observations "
            "(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused,wait_time_status) "
            "VALUES (%s,%s,%s,%s,false,%s)",
            (hour + timedelta(minutes=minute), checkpoint, seconds, vehicles, status),
        )

    raw_response = api_client.get(f"/history/{checkpoint}?hours=24")
    assert raw_response.status_code == 200
    raw = raw_response.json()
    assert raw["resolution"] == "raw"
    assert [(p["vehicles_in_queue"], p["wait_time_status"], p["wait_estimate_seconds"])
            for p in raw["points"]] == [
        (10, "reported", 0),
        (20, "missing", None),
        (30, "legacy_unknown", None),
        (40, "legacy_unknown", 3600),
    ]
    assert [p["wait_time_seconds"] for p in raw["points"]] == [0, 0, 0, 3600]

    hourly_response = api_client.get(f"/history/{checkpoint}?hours=72")
    assert hourly_response.status_code == 200
    hourly = hourly_response.json()
    assert hourly["resolution"] == "hourly"
    assert len(hourly["count_hours"]) == len(hourly["wait_hours"]) == 1
    assert hourly["count_hours"][0]["samples"] == 4
    assert hourly["count_hours"][0]["avg_vehicles"] == 25
    assert hourly["wait_hours"][0]["samples"] == 2
    assert hourly["wait_hours"][0]["avg_wait_seconds"] == 1800
    assert hourly["wait_hours"][0]["max_wait_seconds"] == 3600
    assert len(hourly["points"]) == 1
    assert hourly["points"][0]["samples"] == 1
    assert hourly["points"][0]["avg_wait_seconds"] == 3600
    assert isinstance(hourly["points"][0]["avg_vehicles"], int)


def test_stale_forecast_and_independent_quality(api_client, checkpoint, conn, monkeypatch):
    from avelren import forecast

    fixed_now = datetime(2026, 6, 15, 9, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(forecast, "datetime", Clock)
    target = fixed_now + timedelta(hours=1)
    for week in range(1, 11):
        conn.execute(
            "INSERT INTO observations VALUES (%s, %s, %s, %s, false)",
            (target - timedelta(weeks=week), checkpoint, week * 600, week * 10),
        )

    response = api_client.get(f"/forecast/{checkpoint}?hours=1")
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "ready"
    assert result["points"] == []
    assert result["reason"] == "fresh_measurement_required"

    quality = api_client.get(f"/forecast/{checkpoint}/quality")
    assert quality.status_code == 200
    # Останній тиждень (10 авто) не тренує медіану попередніх 9 тижнів (60).
    assert quality.json()["samples"] == 1
    assert quality.json()["mae_vehicles"] == 50.0
    assert quality.json()["validation_days"] == 7


def test_live_count_anchors_real_sql_forecast(api_client, checkpoint, conn, monkeypatch):
    from avelren import forecast

    fixed_now = datetime(2026, 6, 15, 9, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now.astimezone(tz) if tz else fixed_now.replace(tzinfo=None)

    monkeypatch.setattr(forecast, "datetime", Clock)
    conn.execute(
        "INSERT INTO observations "
        "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) "
        "SELECT t, %s, 600, 37, false FROM generate_series(%s, %s, interval '1 hour') t",
        (checkpoint, fixed_now - timedelta(weeks=10), fixed_now - timedelta(hours=1)),
    )
    conn.execute(
        "INSERT INTO observations VALUES (%s, %s, %s, %s, false)",
        (fixed_now, checkpoint, 0, 188),
    )
    response = api_client.get(f"/forecast/{checkpoint}?hours=24")
    assert response.status_code == 200
    result = response.json()
    assert result["method"] == "current_anchored_neighbors_v1"
    assert len(result["points"]) == 24
    assert all(point["vehicles_expected"] == 188 for point in result["points"])
    assert all(
        point["vehicles_low"] <= point["vehicles_expected"] <= point["vehicles_high"]
        for point in result["points"]
    )
