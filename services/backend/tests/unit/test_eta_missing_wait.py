"""Відсутня оцінка не запускає ETA-повідомлення або помилку derived phase."""

import asyncio
from datetime import UTC, datetime

from avelren.eta import evaluate
from avelren.models import WorkloadItem


def test_missing_wait_skips_eta_query():
    class Connection:
        async def execute(self, *args):
            raise AssertionError("Missing wait must not query ETA targets")

    item = WorkloadItem(id=123, title="Без оцінки", for_vehicle_type=1,
                        vehicle_in_active_queues_counts=80)
    assert asyncio.run(evaluate(Connection(), datetime.now(UTC), [item])) == 0


def test_reported_zero_with_cars_creates_measured_eta_alert():
    at = datetime(2026, 9, 30, 12, tzinfo=UTC)

    class Cursor:
        def __init__(self, *, rows=None, row=None):
            self.rows = rows
            self.row = row

        async def fetchall(self):
            return self.rows

        async def fetchone(self):
            return self.row

    class Connection:
        def __init__(self):
            self.insert_params = None

        async def execute(self, query, params):
            if "FROM eta_targets" in query:
                assert params == ([123],)
                return Cursor(rows=[{
                    "id": 7,
                    "checkpoint_id": 123,
                    "target_at": at,
                    "tolerance_seconds": 0,
                }])
            if "INSERT INTO eta_alerts" in query:
                self.insert_params = params
                return Cursor(row={"id": 9})
            raise AssertionError("Unexpected database query")

    conn = Connection()
    item = WorkloadItem(
        id=123, title="Справжній нуль", for_vehicle_type=1,
        wait_time=0, vehicle_in_active_queues_counts=80,
    )
    assert asyncio.run(evaluate(conn, at, [item])) == 1
    assert conn.insert_params == (7, 123, at, 0, 7)


def test_paused_zero_does_not_create_eta_alert():
    class Connection:
        async def execute(self, *args):
            raise AssertionError("Paused zero must not query ETA targets")

    item = WorkloadItem(
        id=123, title="Призупинено", for_vehicle_type=1,
        wait_time=0, is_paused=True, vehicle_in_active_queues_counts=0,
    )
    assert asyncio.run(evaluate(Connection(), datetime.now(UTC), [item])) == 0
