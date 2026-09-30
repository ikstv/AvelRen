"""Перевірка параметрів реального INSERT без мережі та робочої БД."""

import asyncio
from datetime import UTC, datetime

import pytest

from avelren.db import insert_observations
from avelren.models import WorkloadItem


@pytest.mark.parametrize("value,status", [(None, "missing"), (0, "reported"), (3600, "reported")])
def test_missing_wait_write_preserves_count(value, status):
    captured = []

    class Cursor:
        async def executemany(self, sql, params):
            captured.extend(params)

    class Connection:
        def cursor(self):
            return Cursor()

    item = WorkloadItem(
        id=123,
        title="Тест",
        for_vehicle_type=1,
        wait_time=value,
        vehicle_in_active_queues_counts=80,
    )
    at = datetime(2026, 9, 30, 12, tzinfo=UTC)
    assert asyncio.run(insert_observations(Connection(), at, [item])) == 1
    assert captured == [(at, 123, 0 if value is None else value, 80, False, status)]
