"""Offline rolling 24h evaluation of the exact current-anchored implementation.

Pass a directory of public history JSON files named by checkpoint ID. No network,
no database writes. Hourly proxies cannot prove minute-level/live accuracy.
"""

import argparse
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, median

from avelren.queue_model import KYIV, predict_counts


def slot(at):
    local = at.astimezone(KYIV)
    return local.weekday(), local.hour


def evaluate(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    history = {
        datetime.fromisoformat(p["time"].replace("Z", "+00:00")): p["avg_vehicles"]
        for p in payload["points"]
        if p.get("avg_vehicles") is not None
    }
    end = min(
        max(history), datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    )
    errors = defaultdict(list)
    peaks = defaultdict(list)
    cases = 0
    for origin in sorted(history):
        if (
            not timedelta(hours=24) <= end - origin <= timedelta(days=14)
            or origin.hour % 12
        ):
            continue
        past = {t: v for t, v in history.items() if t < origin}
        anchor_at = origin - timedelta(hours=1)
        if anchor_at not in past:
            continue
        targets = [origin + timedelta(hours=h) for h in range(1, 25)]
        if any(t not in history for t in targets):
            continue
        groups = defaultdict(list)
        for t, v in past.items():
            if t >= origin - timedelta(weeks=12):
                groups[slot(t)].append(v)
        if any(len(groups[slot(t)]) < 2 for t in targets):
            continue
        predicted = predict_counts(
            past, origin, past[anchor_at], targets, current_at=anchor_at
        )
        values = {
            "seasonal": [median(groups[slot(t)]) for t in targets],
            "persistence": [past[anchor_at]] * 24,
            "anchored": [predicted[t]["vehicles_expected"] for t in targets],
        }
        actual = [history[t] for t in targets]
        actual_peak = max(range(24), key=lambda i: actual[i])
        for name, forecast in values.items():
            errors[name].extend(
                abs(a - p) for a, p in zip(actual, forecast, strict=True)
            )
            errors[name + "_near"].extend(
                abs(a - p) for a, p in zip(actual[:3], forecast[:3], strict=True)
            )
            peaks[name].append(
                abs(max(range(24), key=lambda i: forecast[i]) - actual_peak)
            )
        cases += 1
    return {
        "checkpoint": int(path.stem),
        "history_hours": len(history),
        "cases": cases,
        "mae": {k: round(mean(v), 2) for k, v in errors.items()},
        "peak_mae_hours": {k: round(mean(v), 2) for k, v in peaks.items()},
        "limitation": "exploratory evaluation; hourly average is proxy for live count; not untouched holdout",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for cp in (17, 1, 29, 6):
        print(json.dumps(evaluate(args.directory / f"{cp}.json")), flush=True)
