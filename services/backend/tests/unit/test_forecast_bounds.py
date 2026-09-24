"""#16: forecast-quality must not aggregate unbounded history.

`evaluate()` previously scanned ALL of a point's `observations_hourly` — with
years of data this is a time- and memory-unbounded query on every public call to
`/forecast/{id}/quality`. The test proves the query now carries a server-owned
lower time bound; the SQL itself runs against a spy conn, no real DB needed.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from avelren import forecast


class _FakeCursor:
    def __init__(self, row: dict) -> None:
        self._row = row

    async def fetchone(self) -> dict:
        return self._row

    async def fetchall(self) -> list[dict]:
        return self._row


class _SpyConn:
    """Records each execute(sql, params), executing nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple | None = None):  # noqa: ANN201
        self.calls.append((sql, params or ()))
        return _FakeCursor({"n": 0, "mae_hours": None})


class _ForecastConn:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def execute(self, sql: str, params: tuple | None = None):  # noqa: ANN201
        return _FakeCursor(self.rows)


def test_evaluate_query_is_time_bounded() -> None:
    spy = _SpyConn()
    asyncio.run(forecast.evaluate(spy, 123))

    assert spy.calls, "evaluate must run a query"
    sql, params = spy.calls[0]

    # A lower time bound is present in the SQL. Since #111 the aggregate is
    # recomputed inline from raw `observations` (clean_hourly), so the server-owned
    # bound now sits on the raw `time` column rather than the view's `bucket` —
    # same #16 intent (finite, server-set), different column.
    assert "time >=" in sql.lower(), "the evaluate query must bound time from below"
    # ...and is passed as a server-owned since parameter, not from the client.
    assert len(params) >= 2, "a since parameter must be passed"
    since = next((p for p in params if isinstance(p, datetime)), None)
    assert since is not None, "there must be a datetime bound among the parameters"

    window = datetime.now(UTC) - since
    # The window is finite and reasonable (not "all history"). LOOKBACK_WEEKS with margin.
    assert timedelta(0) < window <= timedelta(weeks=forecast.LOOKBACK_WEEKS + 1)


def test_quality_evaluation_holds_out_latest_week() -> None:
    spy = _SpyConn()
    asyncio.run(forecast.evaluate(spy, 123))

    sql, params = spy.calls[0]
    assert "validation" in sql.lower()
    assert "training" in sql.lower()
    assert "FROM validation" in sql
    assert "FROM training" in sql
    # Params: checkpoint, lower bound, upper bound, train/validation split.
    assert len(params) == 5
    assert params[3] == params[4]
    # The upper bound is the start of the current UTC hour, so the in-progress
    # hourly aggregate cannot leak into the holdout as a partial actual.
    assert params[2].minute == params[2].second == params[2].microsecond == 0
    assert params[2] - params[3] == timedelta(days=7)


def test_ready_forecast_requires_eight_samples_for_each_slot(monkeypatch) -> None:
    async def ready(*_args):
        return forecast.Readiness("ready", 8.0, 8, None)

    monkeypatch.setattr(forecast, "readiness", ready)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    target = (now + timedelta(hours=1)).astimezone(forecast.KYIV)
    target_dow = (target.weekday() + 1) % 7
    rows = [
        {
            "dow": dow,
            "hour": hour,
            "p25": 10,
            "p50": 20,
            "p75": 30,
            "vehicles_p25": 1,
            "vehicles_p50": 2,
            "vehicles_p75": 3,
            "samples": 7 if (dow, hour) == (target_dow, target.hour) else 8,
        }
        for dow in range(7)
        for hour in range(24)
    ]

    result = asyncio.run(forecast.forecast(_ForecastConn(rows), 123))

    assert result["status"] == "ready"
    assert all(
        point["time"] != now + timedelta(hours=1) for point in result["points"]
    )
