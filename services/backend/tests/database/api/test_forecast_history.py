"""Прогноз на синтетичній історії через справжні SQL та публічний API."""

from datetime import UTC, datetime, timedelta


def test_hourly_vehicle_range_and_independent_quality(api_client, checkpoint, conn, monkeypatch):
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
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert datetime.fromisoformat(point["time"]) == target
    assert point["vehicles_expected"] == 55
    assert point["vehicles_low"] == 32
    assert point["vehicles_high"] == 77
    assert point["samples"] == 10

    quality = api_client.get(f"/forecast/{checkpoint}/quality")
    assert quality.status_code == 200
    # Останній тиждень (10 авто) не тренує медіану попередніх 9 тижнів (60).
    assert quality.json()["samples"] == 1
    assert quality.json()["mae_vehicles"] == 50.0
    assert quality.json()["validation_days"] == 7
