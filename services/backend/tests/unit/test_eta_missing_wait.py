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
