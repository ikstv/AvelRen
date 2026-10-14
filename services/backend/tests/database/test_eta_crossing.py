"""ETA перетинає ціль між двома збереженими спостереженнями."""

import asyncio
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from avelren import eta
from avelren.models import WorkloadItem


def exercise(database, history, current_wait, expected, *, created_offset=-61, paused=False):
    at = datetime.now(UTC)
    target_at = at + timedelta(hours=4)
    with psycopg.connect(database("admin")) as conn:
        conn.execute(
            "INSERT INTO checkpoints(id,title,for_vehicle_type) "
            "VALUES(17,'fixture',1),(18,'other',1)"
        )
        device = conn.execute(
            "INSERT INTO devices(secret_hash) VALUES('fixture') RETURNING id"
        ).fetchone()[0]
        target = conn.execute(
            "INSERT INTO eta_targets(device_id,checkpoint_id,target_at,"
            "tolerance_seconds,created_at) "
            "VALUES(%s,17,%s,900,%s) RETURNING id",
            (device, target_at, at + timedelta(seconds=created_offset)),
        ).fetchone()[0]
        # Collector replay commits the current observation before ETA evaluation.
        for offset, wait, status, is_paused, checkpoint in [
            *history,
            (0, current_wait or 0, "missing" if current_wait is None else "reported", paused, 17),
        ]:
            conn.execute(
                "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,wait_time_status,"
                "vehicles_in_queue,is_paused) VALUES(%s,%s,%s,%s,0,%s)",
                (at + timedelta(seconds=offset), checkpoint, wait, status, is_paused),
            )

    async def evaluate_twice():
        async with await psycopg.AsyncConnection.connect(
            database("collector"), row_factory=dict_row
        ) as conn:
            item = WorkloadItem(
                id=17, title="fixture", for_vehicle_type=1, wait_time=current_wait, is_paused=paused
            )
            assert await eta.evaluate(conn, at, [item]) == expected
            assert await eta.evaluate(conn, at, [item]) == 0

    asyncio.run(evaluate_twice())
    with psycopg.connect(database("admin")) as conn:
        rows = conn.execute(
            "SELECT target_id,eta_at_trigger,wait_seconds_at_trigger,status FROM eta_alerts"
        ).fetchall()
    assert rows == (
        [(target, at + timedelta(seconds=current_wait), current_wait, "pending")]
        if expected
        else []
    )


def test_forward_jump_over_entire_window_creates_one_pending_alert(database):
    exercise(database, [(-60, 10800, "reported", False, 17)], 18000, 1)


@pytest.mark.parametrize(
    "history,current_wait,expected,created_offset,paused",
    [
        pytest.param(
            [(-60, 10800, "reported", False, 17)], 18000, 0, -30, False, id="before-subscription"
        ),
        pytest.param([], 18000, 0, -61, False, id="no-history-current-row-excluded"),
        pytest.param(
            [(-60, 10800, "reported", False, 18)], 18000, 0, -61, False, id="other-checkpoint"
        ),
        pytest.param(
            [(-120, 10800, "reported", False, 17), (-60, 0, "missing", False, 17)],
            18000,
            0,
            -180,
            False,
            id="missing-breaks-history",
        ),
        pytest.param(
            [(-60, 0, "reported", True, 17)], 18000, 0, -61, False, id="paused-zero-previous"
        ),
        pytest.param(
            [(-60, 10800, "reported", True, 17)],
            18000,
            1,
            -61,
            False,
            id="paused-positive-previous-valid",
        ),
        pytest.param(
            [(-60, 10800, "legacy_unknown", False, 17)],
            18000,
            1,
            -61,
            False,
            id="legacy-positive-valid",
        ),
        pytest.param(
            [(-60, 0, "legacy_unknown", False, 17)], 18000, 0, -61, False, id="legacy-zero-unknown"
        ),
        pytest.param(
            [(-60, 18000, "reported", False, 17)], 10800, 0, -61, False, id="reverse-crossing"
        ),
        pytest.param(
            [(-60, 18000, "reported", False, 17)], 19000, 0, -61, False, id="already-after-target"
        ),
        pytest.param(
            [(-60, 10800, "reported", False, 17)], None, 0, -61, False, id="current-missing"
        ),
        pytest.param(
            [(-60, 10800, "reported", False, 17)], 0, 0, -61, True, id="current-paused-zero"
        ),
        pytest.param(
            [(-60, 10800, "reported", False, 17)],
            18000,
            1,
            -61,
            True,
            id="current-paused-positive-valid",
        ),
        pytest.param(
            [(-60, 0, "missing", False, 17)],
            14400,
            1,
            -61,
            False,
            id="in-window-with-missing-history",
        ),
        pytest.param([], 13500, 1, -61, False, id="window-lower-bound-inclusive"),
        pytest.param([], 15300, 1, -61, False, id="window-upper-bound-inclusive"),
        pytest.param(
            [(-60, 10800, "reported", False, 17)],
            18000,
            1,
            -60,
            False,
            id="history-at-creation-inclusive",
        ),
        pytest.param(
            [(-60, 10800, "reported", False, 17)], 18000, 0, 1, False, id="current-before-creation"
        ),
    ],
)
def test_crossing_boundaries(database, history, current_wait, expected, created_offset, paused):
    exercise(
        database, history, current_wait, expected, created_offset=created_offset, paused=paused
    )
