"""#16: forecast-quality не сміє агрегувати необмежену історію.

`evaluate()` раніше сканував УСІ `observations_hourly` пункту — з роками даних
це необмежений за часом і пам'яттю запит на кожен публічний виклик
`/forecast/{id}/quality`. Тест доводить, що запит тепер несе server-owned нижню
межу за часом; сам SQL виконується проти spy-conn, реальна БД не потрібна.
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
    """Фіксує кожен execute(sql, params), нічого не виконуючи."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, params: tuple | None = None):  # noqa: ANN201
        self.calls.append((sql, params or ()))
        return _FakeCursor({"n": 0, "mae_hours": None})


def test_evaluate_query_is_time_bounded() -> None:
    spy = _SpyConn()
    asyncio.run(forecast.evaluate(spy, 123))

    assert spy.calls, "evaluate має виконати запит"
    sql, params = spy.calls[0]

    # Нижня межа за часом присутня в SQL...
    assert "bucket >=" in sql.lower(), "запит evaluate має обмежувати bucket знизу"
    # ...і передається server-owned since-параметром, не з клієнта.
    assert len(params) >= 2, "має бути переданий since-параметр"
    since = next((p for p in params if isinstance(p, datetime)), None)
    assert since is not None, "серед параметрів має бути datetime-межа"

    window = datetime.now(UTC) - since
    # Вікно скінченне й розумне (не «вся історія»). LOOKBACK_WEEKS з запасом.
    assert timedelta(0) < window <= timedelta(weeks=forecast.LOOKBACK_WEEKS + 1)
