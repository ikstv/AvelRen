"""Відкладений період anchored backtest не повинен бачити майбутнє."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tools.forecast_current_backtest import evaluate


def test_explicit_holdout_excludes_earlier_origins_and_later_observations(tmp_path):
    first = datetime(2026, 8, 1, tzinfo=UTC)
    holdout_start = datetime(2026, 9, 27, tzinfo=UTC)
    holdout_end = datetime(2026, 9, 29, tzinfo=UTC)
    points = [
        {"time": (first + timedelta(hours=i)).isoformat(), "avg_vehicles": 50 + i % 24,
         "samples": 1}
        for i in range(int((holdout_end - first).total_seconds() // 3600) + 1)
    ]
    path = tmp_path / "17.json"
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": points}),
        encoding="utf-8",
    )

    before = evaluate(path, holdout_start=holdout_start, holdout_end=holdout_end)
    points.extend(
        {"time": (holdout_end + timedelta(hours=i)).isoformat(),
         "avg_vehicles": 9999, "samples": 1}
        for i in range(1, 25)
    )
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": points}),
        encoding="utf-8",
    )
    after = evaluate(path, holdout_start=holdout_start, holdout_end=holdout_end)

    assert before["method"] == "current_anchored_neighbors_v1"
    assert before["history_source"] == "count_hours"
    assert before["cases"] == 3
    assert before["holdout_start"] == holdout_start.isoformat()
    assert before["holdout_end"] == holdout_end.isoformat()
    assert "post-selection" in before["limitation"]
    assert before["mae"] == after["mae"]
    assert before["peak_mae_hours"] == after["peak_mae_hours"]


def test_empty_holdout_reports_no_cases_instead_of_crashing(tmp_path):
    path = tmp_path / "17.json"
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": [
            {"time": "2026-09-27T00:00:00+00:00", "avg_vehicles": 50, "samples": 1}
        ]}),
        encoding="utf-8",
    )

    result = evaluate(path, holdout_start=datetime(2026, 9, 28, tzinfo=UTC))

    assert result["cases"] == 0
    assert result["mae"] == {}
    assert result["peak_mae_hours"] == {}


def test_explicit_holdout_rejects_legacy_wait_filtered_history(tmp_path):
    path = tmp_path / "17.json"
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [
            {"time": "2026-09-27T00:00:00+00:00", "avg_vehicles": 50}
        ]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="count_hours"):
        evaluate(path, holdout_start=datetime(2026, 9, 25, tzinfo=UTC))


def test_explicit_holdout_does_not_silently_truncate_to_last_fourteen_days(tmp_path):
    first = datetime(2026, 8, 1, tzinfo=UTC)
    end = datetime(2026, 9, 29, tzinfo=UTC)
    count_hours = [
        {"time": (first + timedelta(hours=i)).isoformat(), "avg_vehicles": 50 + i % 24,
         "samples": 1}
        for i in range(int((end - first).total_seconds() // 3600) + 1)
    ]
    path = tmp_path / "17.json"
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": count_hours}),
        encoding="utf-8",
    )

    result = evaluate(
        path,
        holdout_start=datetime(2026, 9, 10, tzinfo=UTC),
        holdout_end=end,
    )

    assert result["cases"] == 37


def test_holdout_skips_window_without_recent_trend_instead_of_crashing(tmp_path):
    first = datetime(2026, 8, 1, tzinfo=UTC)
    end = datetime(2026, 9, 29, tzinfo=UTC)
    missing = datetime(2026, 9, 27, 22, tzinfo=UTC)
    count_hours = [
        {"time": at.isoformat(), "avg_vehicles": 50 + at.hour, "samples": 1}
        for i in range(int((end - first).total_seconds() // 3600) + 1)
        if (at := first + timedelta(hours=i)) != missing
    ]
    path = tmp_path / "17.json"
    path.write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": count_hours}),
        encoding="utf-8",
    )

    result = evaluate(
        path,
        holdout_start=datetime(2026, 9, 27, tzinfo=UTC),
        holdout_end=end,
    )

    assert result["cases"] == 0
    assert result["mae"] == {}


def test_cli_labels_the_selected_model_and_holdout_period(tmp_path):
    (tmp_path / "17.json").write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": [
            {"time": "2026-09-27T00:00:00+00:00", "avg_vehicles": 50, "samples": 1}
        ]}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[4] / "tools/forecast_current_backtest.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(script.parent.parent / "services/backend/src")

    command = subprocess.run(
        [
            sys.executable,
            str(script),
            str(tmp_path),
            "--checkpoint",
            "17",
            "--holdout-start",
            "2026-09-28T00:00:00+00:00",
            "--holdout-end",
            "2026-09-29T00:00:00+00:00",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert command.returncode == 0, command.stderr
    result = json.loads(command.stdout)
    assert result["method"] == "current_anchored_neighbors_v1"
    assert result["holdout_start"] == "2026-09-28T00:00:00+00:00"
    assert result["holdout_end"] == "2026-09-27T00:00:00+00:00"
    assert result["cases"] == 0


def test_cli_rejects_legacy_history_without_traceback(tmp_path):
    (tmp_path / "17.json").write_text(
        json.dumps({"resolution": "hourly", "points": [
            {"time": "2026-09-27T00:00:00+00:00", "avg_vehicles": 50}
        ]}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[4] / "tools/forecast_current_backtest.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(script.parent.parent / "services/backend/src")

    command = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "--checkpoint", "17",
         "--holdout-start", "2026-09-25T00:00:00+00:00"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert command.returncode != 0
    assert "count_hours" in command.stderr
    assert "Traceback" not in command.stderr


def test_cli_rejects_naive_holdout_datetime(tmp_path):
    (tmp_path / "17.json").write_text(
        json.dumps({"resolution": "hourly", "points": [], "count_hours": [
            {"time": "2026-09-27T00:00:00+00:00", "avg_vehicles": 50, "samples": 1}
        ]}),
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[4] / "tools/forecast_current_backtest.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(script.parent.parent / "services/backend/src")

    command = subprocess.run(
        [sys.executable, str(script), str(tmp_path), "--checkpoint", "17",
         "--holdout-start", "2026-09-25"],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert command.returncode != 0
    assert "timezone" in command.stderr.lower()
    assert "Traceback" not in command.stderr
