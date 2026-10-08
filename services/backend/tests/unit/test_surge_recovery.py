"""Відновлення після прогалини без запитів до джерела."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest

from avelren import surge_store
from avelren.surge_model import SurgePrediction

T = datetime(2026, 10, 8, 19, tzinfo=UTC)


class Connection:
    def __init__(self, already_failed=False):
        self.stored = dict(
            forecast_armed=True,
            last_observation_at=None,
            last_forecast_hour=T if already_failed else None,
            last_growth_at=None,
        )
        self.predictions = (
            [dict(issued_at=T, score=None, reason="insufficient_history")] if already_failed else []
        )
        self.now = T
        self.query = ""

    def cursor(self, **kw):
        return self

    @asynccontextmanager
    async def transaction(self):
        yield

    async def execute(self, query, params=()):
        self.query = query
        if "INSERT INTO surge_predictions" in query:
            self.predictions.append(dict(issued_at=params[1], score=params[5], reason=params[6]))
        elif "UPDATE surge_checkpoint_state SET" in query:
            self.stored.update(
                last_observation_at=params[0],
                last_forecast_hour=params[1],
                forecast_armed=params[2],
                last_growth_at=params[3],
            )

    async def fetchone(self):
        if "surge_checkpoint_state" in self.query:
            return dict(self.stored)
        if "INSERT INTO surge_predictions" in self.query:
            return dict(id=len(self.predictions))
        if "FROM surge_predictions" in self.query:
            return self.predictions[-1] if self.predictions else None
        raise AssertionError(self.query)

    async def fetchall(self):
        if "FROM observations" in self.query:
            return [dict(time=self.now, vehicles_in_queue=100, is_paused=False)]
        if "FROM surge_events" in self.query:
            return []
        raise AssertionError(self.query)


@pytest.mark.parametrize("cp", [1, 6, 17, 29])
@pytest.mark.parametrize("already_failed", [False, True])
def test_failed_hour_recovers_on_fresh_minute_once(monkeypatch, cp, already_failed):
    c = Connection(already_failed)
    calls = []

    def model(checkpoint, observations, issued):
        calls.append(issued)
        return SurgePrediction(
            issued,
            issued + timedelta(hours=1),
            issued + timedelta(hours=24),
            None if issued == T else 0.1,
            "insufficient_history" if issued == T else None,
        )

    monkeypatch.setattr(surge_store, "predict_surge", model)
    monkeypatch.setattr(surge_store, "detect_growth", lambda *args: None)

    async def run():
        if not already_failed:
            await surge_store.process_checkpoint(c, cp, T)
        c.now = T + timedelta(minutes=1)
        await surge_store.process_checkpoint(c, cp, c.now)
        await surge_store.process_checkpoint(c, cp, c.now)
        c.now += timedelta(minutes=1)
        await surge_store.process_checkpoint(c, cp, c.now)

    asyncio.run(run())
    assert len(c.predictions) == 2
    assert c.predictions[-1]["score"] == 0.1
    assert calls.count(T + timedelta(minutes=1)) == 1
