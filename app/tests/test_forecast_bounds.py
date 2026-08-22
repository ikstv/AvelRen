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


class _SpyConn:
    """Records each execute(sql, params), executing nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple | None = None):  # noqa: ANN201
        self.calls.append((sql, params or ()))
        return _FakeCursor({"n": 0, "mae_hours": None})


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
