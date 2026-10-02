"""Епізоди не дублюються й не оживають після факту без rearm."""

from datetime import UTC, datetime, timedelta

import pytest

from avelren.surge_events import SurgeState, advance_state
from avelren.surge_model import SurgePrediction

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


def p(score=0.99, at=T):
    return SurgePrediction(
        at,
        at + timedelta(hours=1),
        at + timedelta(hours=24),
        score,
        "gap" if score is None else None,
    )


EMPTY_STATE = SurgeState()


def step(state=EMPTY_STATE, prediction=None, growth=0, at=T, now=None):
    return advance_state(state, prediction, growth, at, now or at)


def test_positive_updates_single_forecast_and_below_rearms():
    a = step(prediction=p())
    assert a.started == ("surge_forecast",)
    b = step(a.state, p(at=T + timedelta(hours=1)), at=T + timedelta(hours=1))
    assert b.started == ()
    assert b.state.forecast.started_at == T
    assert b.state.forecast.expires_at == T + timedelta(minutes=125)
    c = step(b.state, p(0.2, at=T + timedelta(hours=1)), at=T + timedelta(hours=1))
    assert c.closed == (("surge_forecast", "below_threshold"),)
    assert c.state.forecast_armed
    assert step(c.state, p(at=T + timedelta(hours=2)), at=T + timedelta(hours=2)).started == (
        "surge_forecast",
    )


def test_forecast_expires_without_next_hour_even_when_observations_fresh():
    a = step(prediction=p())
    assert step(a.state, at=T + timedelta(minutes=64)).closed == ()
    assert step(a.state, at=T + timedelta(minutes=65)).closed == (("surge_forecast", "timeout"),)


def test_fact_closes_forecast_and_blocks_high_after_quiet_end():
    a = step(prediction=p())
    b = step(a.state, p(at=T + timedelta(minutes=1)), 20, at=T + timedelta(minutes=1))
    assert b.started == ("surge_started",)
    assert b.closed == (("surge_forecast", "fact_started"),)
    assert not b.state.forecast_armed
    c = step(b.state, p(at=T + timedelta(minutes=29)), 0, at=T + timedelta(minutes=29))
    assert c.started == ()
    d = step(c.state, p(at=T + timedelta(minutes=31)), 0, at=T + timedelta(minutes=31))
    assert d.state.fact is None
    assert d.started == ()
    assert step(d.state, p(at=T + timedelta(hours=1)), at=T + timedelta(hours=1)).started == ()
    e = step(d.state, p(0.1, at=T + timedelta(hours=1)), at=T + timedelta(hours=1))
    assert step(e.state, p(at=T + timedelta(hours=2)), at=T + timedelta(hours=2)).started == (
        "surge_forecast",
    )


@pytest.mark.parametrize("minutes", [1, 29, 30])
def test_qualifying_windows_within_30_minutes_are_one_fact(minutes):
    a = step(growth=20)
    b = step(a.state, growth=30, at=T + timedelta(minutes=minutes))
    assert b.started == ()
    assert b.state.fact.started_at == T
    assert b.state.fact.expires_at == T + timedelta(minutes=minutes + 30)


def test_fact_after_long_gap_is_new_episode():
    a = step(growth=20)
    b = step(a.state, growth=20, at=T + timedelta(minutes=31))
    assert b.closed == (("surge_started", "timeout"),)
    assert b.started == ("surge_started",)
    assert b.state.fact.started_at == T + timedelta(minutes=31)


@pytest.mark.parametrize("growth", [None, 0, 19])
def test_no_fact_below_threshold(growth):
    assert step(growth=growth).started == ()


def test_stale_closes_and_replay_does_not_create_voice():
    a = step(prediction=p())
    b = step(a.state, p(), 20, now=T + timedelta(minutes=4))
    assert b.closed == (("surge_forecast", "stale"),)
    assert b.started == ()
    assert step(growth=20, now=T + timedelta(minutes=4)).started == ()


def test_replayed_observation_cannot_extend_fact_expiry():
    a = step(growth=20)
    b = step(a.state, growth=20, at=T, now=T + timedelta(minutes=1))
    assert b.state.fact.expires_at == a.state.fact.expires_at
    assert b.started == ()


def test_invalid_prediction_closes_forecast_without_fake_zero():
    a = step(prediction=p())
    b = step(a.state, p(None))
    assert b.closed == (("surge_forecast", "unavailable"),)


@pytest.mark.parametrize("bad", [T.replace(tzinfo=None), T + timedelta(seconds=1)])
def test_naive_rejected_future_does_not_start(bad):
    if bad.tzinfo is None:
        with pytest.raises(ValueError):
            step(at=bad)
    else:
        assert step(growth=100, at=bad, now=T).started == ()


def test_positive_after_expired_episode_creates_new_event():
    a = step(prediction=p())
    later = T + timedelta(minutes=66)
    b = step(a.state, p(at=later), at=later)
    assert b.closed == (("surge_forecast", "timeout"),)
    assert b.started == ("surge_forecast",)
    assert b.state.forecast.started_at == later
