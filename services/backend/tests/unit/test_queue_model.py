from datetime import UTC, datetime, timedelta

from avelren.queue_model import predict_counts


def history(now):
    return {now - timedelta(hours=i): 37.0 for i in range(1, 24 * 28)}


def test_current_188_is_not_replaced_by_historical_37():
    now = datetime(2026, 9, 24, 14, tzinfo=UTC)
    targets = [now + timedelta(hours=h) for h in range(1, 25)]
    result = predict_counts(history(now), now, 188, targets)
    assert len(result) == 24
    assert all(p["vehicles_expected"] == 188 for p in result.values())
    assert all(
        p["vehicles_low"] <= p["vehicles_expected"] <= p["vehicles_high"] for p in result.values()
    )


def test_future_and_partial_hour_cannot_leak_into_training():
    now = datetime(2026, 9, 24, 14, tzinfo=UTC)
    target = now + timedelta(hours=1)
    clean = history(now)
    polluted = {**clean, now: 999999, target: 999999}
    assert predict_counts(clean, now, 188, [target]) == predict_counts(polluted, now, 188, [target])


def test_missing_recent_history_does_not_invent_a_trend():
    now = datetime(2026, 9, 24, 14, tzinfo=UTC)
    sparse = history(now)
    del sparse[now - timedelta(hours=2)]
    assert predict_counts(sparse, now, 188, [now + timedelta(hours=1)]) == {}


def test_near_hour_uses_fractional_time_since_measurement():
    now = datetime(2026, 9, 24, 14, 59, tzinfo=UTC)
    start = now.replace(minute=0)
    hourly = {at: float(at.hour * 10) for at in history(start)}
    target = start + timedelta(hours=1)
    result = predict_counts(hourly, now, 188, [target], current_at=now)
    assert abs(result[target]["vehicles_expected"] - 188) <= 1


def test_negative_predictions_are_clipped():
    now = datetime(2026, 9, 24, 14, tzinfo=UTC)
    hourly = {at: float((23 - at.hour) * 100) for at in history(now)}
    result = predict_counts(hourly, now, 0, [now + timedelta(hours=h) for h in range(1, 25)])
    assert all(p["vehicles_low"] >= 0 for p in result.values())
