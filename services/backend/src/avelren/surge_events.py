"""Чисті переходи прогнозних і фактичних епізодів."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .surge_model import SCORE_THRESHOLD, SurgePrediction

FORECAST = "surge_forecast"
FACT = "surge_started"


@dataclass(frozen=True)
class Episode:
    started_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class SurgeState:
    forecast: Episode | None = None
    fact: Episode | None = None
    forecast_armed: bool = True
    last_observation_at: datetime | None = None


@dataclass(frozen=True)
class SurgeDecision:
    state: SurgeState
    started: tuple[str, ...]
    closed: tuple[tuple[str, str], ...]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(UTC)


def advance_state(
    state: SurgeState,
    prediction: SurgePrediction | None,
    growth: int | None,
    observed_at: datetime,
    now: datetime,
) -> SurgeDecision:
    observed_at, now = utc(observed_at), utc(now)
    fresh = timedelta(0) <= now - observed_at <= timedelta(minutes=3)
    forecast, fact, armed = state.forecast, state.fact, state.forecast_armed
    started = []
    closed = []
    if not fresh:
        if forecast:
            closed.append((FORECAST, "stale"))
        if fact:
            closed.append((FACT, "stale"))
            armed = False
        return SurgeDecision(
            replace(state, forecast=None, fact=None, forecast_armed=armed), (), tuple(closed)
        )
    if forecast and now >= forecast.expires_at:
        forecast = None
        closed.append((FORECAST, "timeout"))
    new_observation = state.last_observation_at is None or observed_at > state.last_observation_at
    qualifying = new_observation and growth is not None and growth >= 20
    # A qualifying window exactly 30 minutes later belongs to the same episode.
    if fact and (now > fact.expires_at or (now == fact.expires_at and not qualifying)):
        fact = None
        closed.append((FACT, "timeout"))
    if qualifying:
        if fact is None:
            fact = Episode(observed_at, observed_at, observed_at + timedelta(minutes=30))
            started.append(FACT)
        else:
            fact = replace(
                fact, updated_at=observed_at, expires_at=observed_at + timedelta(minutes=30)
            )
        armed = False
    if fact:
        if forecast:
            closed.append((FORECAST, "fact_started"))
            forecast = None
        armed = False
    elif prediction is not None:
        score = prediction.score
        prediction_fresh = timedelta(0) <= now - utc(prediction.issued_at) <= timedelta(minutes=3)
        if score is None or not prediction_fresh:
            if forecast:
                closed.append((FORECAST, "unavailable"))
                forecast = None
        elif score < SCORE_THRESHOLD:
            if forecast:
                closed.append((FORECAST, "below_threshold"))
                forecast = None
            armed = True
        elif forecast is not None:
            issued = utc(prediction.issued_at)
            if issued > forecast.updated_at:
                forecast = replace(
                    forecast, updated_at=issued, expires_at=issued + timedelta(minutes=65)
                )
        elif armed:
            issued = utc(prediction.issued_at)
            forecast = Episode(issued, issued, issued + timedelta(minutes=65))
            started.append(FORECAST)
    if forecast and now >= forecast.expires_at:
        forecast = None
        closed.append((FORECAST, "timeout"))
    last = max(observed_at, state.last_observation_at) if state.last_observation_at else observed_at
    return SurgeDecision(SurgeState(forecast, fact, armed, last), tuple(started), tuple(closed))
