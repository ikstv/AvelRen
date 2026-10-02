import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from pathlib import Path

import pytest

from avelren.surge_model import Observation, detect_growth, predict_surge

NOW = datetime(2026, 10, 2, 10, tzinfo=UTC)


def history(now=NOW, count=None, paused=False):
    return [
        Observation(
            now - timedelta(minutes=240 - i), 200 + i // 10 if count is None else count, paused
        )
        for i in range(241)
    ]


def test_frozen_golden_score():
    prediction = predict_surge(17, history(), NOW)
    assert prediction.reason is None
    expected = json.loads((Path(__file__).parent / "fixtures/surge_model_cases.json").read_text())[
        "score"
    ]
    assert prediction.score == pytest.approx(expected, abs=1e-10)
    assert prediction.window_start == NOW + timedelta(hours=1)
    assert prediction.window_end == NOW + timedelta(hours=24)


@pytest.mark.parametrize("delta,expected", [(19, 19), (20, 20), (200, 200)])
def test_growth_reports_measurement_not_trigger_threshold(delta, expected):
    rows = history(count=100)
    rows[-1] = replace(rows[-1], vehicles=100 + delta)
    assert detect_growth(rows, NOW) == expected


def test_future_measurements_do_not_change_prediction():
    base = history()
    future = base + [Observation(NOW + timedelta(minutes=1), 999999, True)]
    assert predict_surge(17, future, NOW) == predict_surge(17, base, NOW)


@pytest.mark.parametrize("seconds,available", [(30, True), (31, False)])
def test_endpoint_tolerance(seconds, available):
    rows = history()
    rows[-6] = replace(rows[-6], time=rows[-6].time + timedelta(seconds=seconds))
    assert (detect_growth(rows, NOW) is not None) == available


@pytest.mark.parametrize("seconds,available", [(90, True), (91, False)])
def test_internal_gap(seconds, available):
    rows = history()
    rows[-3] = replace(rows[-3], time=rows[-3].time + timedelta(seconds=seconds - 60))
    assert (predict_surge(17, rows, NOW).score is not None) == available


def test_stale_data_is_unknown_not_zero():
    p = predict_surge(17, history(), NOW + timedelta(minutes=3, seconds=1))
    assert p.score is None
    assert p.reason == "stale_measurement"


def test_unsupported_checkpoint_is_unknown():
    p = predict_surge(99, history(), NOW)
    assert p.score is None
    assert p.reason == "unsupported_checkpoint"


@pytest.mark.parametrize("count,paused", [(0, False), (100, True)])
def test_zero_count_and_paused_are_valid_inputs(count, paused):
    p = predict_surge(17, history(count=count, paused=paused), NOW)
    assert p.reason is None
    assert isfinite(p.score)


def test_missing_long_history_has_reason():
    p = predict_surge(17, history()[100:], NOW)
    assert p.score is None
    assert p.reason == "insufficient_history"


@pytest.mark.parametrize("remove,available", [(12, True), (13, False)])
def test_long_window_coverage_boundary(remove, available):
    rows = history()
    # Drop isolated old records, outside strict last60min window.
    absent = {2 + i * 5 for i in range(remove)}
    rows = [r for i, r in enumerate(rows) if i not in absent]
    assert (predict_surge(17, rows, NOW).score is not None) == available


def test_dst_absolute_horizon():
    now = datetime(2026, 10, 25, 1, tzinfo=UTC)
    p = predict_surge(17, history(now=now), now)
    assert p.window_end - now == timedelta(hours=24)
    assert p.window_start - now == timedelta(hours=1)


@pytest.mark.parametrize("mutation", ["duplicate", "negative", "naive"])
def test_invalid_measurements_are_rejected(mutation):
    rows = history()
    if mutation == "duplicate":
        rows.append(rows[-1])
    if mutation == "negative":
        rows[-1] = replace(rows[-1], vehicles=-1)
    if mutation == "naive":
        rows[-1] = replace(rows[-1], time=rows[-1].time.replace(tzinfo=None))
    p = predict_surge(17, rows, NOW)
    assert p.score is None
    assert p.reason == "invalid_observations"


def test_no_data_is_unknown():
    assert predict_surge(17, [], NOW).reason == "insufficient_history"


def test_corrupted_model_fails_closed(tmp_path):
    from avelren.surge_model import load_model

    model = tmp_path / "broken.json"
    model.write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        load_model(model)


def test_local_dst_input_preserves_absolute_horizon():
    from zoneinfo import ZoneInfo

    local_now = datetime(2026, 10, 25, 2, tzinfo=ZoneInfo("Europe/Kyiv"))
    p = predict_surge(17, history(now=local_now.astimezone(UTC)), local_now)
    assert p.window_start.astimezone(UTC) - local_now.astimezone(UTC) == timedelta(hours=1)
    assert p.window_end.astimezone(UTC) - local_now.astimezone(UTC) == timedelta(hours=24)
