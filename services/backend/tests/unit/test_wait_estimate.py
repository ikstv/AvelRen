"""Відсутня оцінка не є нулем, а ETA не використовує непідтверджений нуль."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from avelren.models import WorkloadItem


@pytest.mark.parametrize(
    ("extra", "seconds", "status"),
    [
        ({}, None, "missing"),
        ({"wait_time": None}, None, "missing"),
        ({"wait_time": 0}, 0, "reported"),
        ({"wait_time": 3600}, 3600, "reported"),
    ],
)
def test_workload_preserves_missing_and_zero(extra, seconds, status):
    item = WorkloadItem.model_validate(
        {
            "id": 123,
            "title": "Тест",
            "for_vehicle_type": 1,
            "vehicle_in_active_queues_counts": 80,
            **extra,
        }
    )
    assert item.wait_time == seconds
    assert item.wait_time_status == status
    assert item.vehicles_in_queue == 80


@pytest.mark.parametrize("value", [True, False, 1.5, 3600.0, "3600", -1])
def test_workload_rejects_invalid_wait(value):
    with pytest.raises(ValidationError):
        WorkloadItem.model_validate(
            {"id": 123, "title": "Тест", "for_vehicle_type": 1, "wait_time": value}
        )


def test_source_cannot_override_wait_status():
    item = WorkloadItem.model_validate(
        {"id": 123, "title": "Тест", "for_vehicle_type": 1, "wait_time_status": "reported"}
    )
    assert item.wait_time_status == "missing"


@pytest.mark.parametrize(
    ("seconds", "status", "expected"),
    [
        (0, "reported", 0),
        (3600, "reported", 3600),
        (0, "missing", None),
        (3600, "missing", None),
        (0, "legacy_unknown", None),
        (3600, "legacy_unknown", 3600),
        (-1, "legacy_unknown", None),
        (-1, "reported", None),
        (3600, "future_status", None),
    ],
)
def test_wait_read_policy(seconds, status, expected):
    from avelren.wait_estimate import usable_wait_seconds

    assert usable_wait_seconds(seconds, status) == expected


@pytest.mark.parametrize(
    ("seconds", "status", "paused", "expected_seconds", "expected_eta"),
    [
        (0, "reported", False, 0, datetime(2026, 9, 30, 12, tzinfo=UTC)),
        (0, "reported", True, 0, None),
        (0, "missing", False, None, None),
        (0, "legacy_unknown", False, None, None),
        (3600, "reported", True, 3600, datetime(2026, 9, 30, 13, tzinfo=UTC)),
        (3600, "legacy_unknown", False, 3600, datetime(2026, 9, 30, 13, tzinfo=UTC)),
    ],
)
def test_measured_wait_eta(seconds, status, paused, expected_seconds, expected_eta):
    from avelren.wait_estimate import measured_wait

    result = measured_wait(datetime(2026, 9, 30, 12, tzinfo=UTC), seconds, status, paused)
    assert result == {"status": status, "seconds": expected_seconds, "entry_eta": expected_eta}
