"""Regression coverage for forecast quality output serialization."""

import asyncio

from avelren import forecast


class _Cursor:
    async def fetchone(self) -> dict:
        return {"n": 1, "mae_hours": 0.0, "mae_vehicles": 0.0}


class _QualityConn:
    async def execute(self, _sql: str, _params: tuple | None = None) -> _Cursor:
        return _Cursor()


def test_evaluate_preserves_zero_mae_hours() -> None:
    result = asyncio.run(forecast.evaluate(_QualityConn(), 123))

    assert result["mae_hours"] == 0.0
