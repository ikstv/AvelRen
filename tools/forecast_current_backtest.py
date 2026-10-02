"""Offline rolling 24h evaluation of the exact current-anchored implementation.

Pass a directory of public history JSON files named by checkpoint ID. Explicit
holdouts require independent ``count_hours`` from the new API; legacy ``points``
are only allowed for exploratory runs. No network or database writes. Hourly
proxies cannot prove minute-level/live accuracy.
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


def aware_datetime(value):
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected ISO datetime with timezone") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError("holdout datetime requires a timezone")
    return result


def evaluate(path, *, holdout_start=None, holdout_end=None):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("resolution") == "hourly" and "count_hours" in payload:
        source_name = "count_hours"
    elif holdout_start is not None:
        raise ValueError("explicit holdout requires independent count_hours history")
    else:
        source_name = "points"
    history = {
        datetime.fromisoformat(p["time"].replace("Z", "+00:00")): p["avg_vehicles"]
        for p in payload[source_name]
        if p.get("avg_vehicles") is not None
    }
    end = min(
        max(history),
        datetime.now(UTC).replace(minute=0, second=0, microsecond=0),
        holdout_end or datetime.max.replace(tzinfo=UTC),
    )
    errors = defaultdict(list)
    peaks = defaultdict(list)
    cases = 0
    first_origin = holdout_start or end - timedelta(days=14)
    for origin in sorted(history):
        if (
            end - origin < timedelta(hours=24)
            or origin.hour % 12
            or origin < first_origin
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
        if any(t not in predicted for t in targets):
            continue
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
        "method": "current_anchored_neighbors_v1",
        "history_source": source_name,
        "holdout_start": holdout_start.isoformat() if holdout_start else None,
        "holdout_end": end.isoformat(),
        "history_hours": sum(at <= end for at in history),
        "cases": cases,
        "mae": {k: round(mean(v), 2) for k, v in errors.items()},
        "peak_mae_hours": {k: round(mean(v), 2) for k, v in peaks.items()},
        "limitation": (
            "operator-defined post-selection window; hourly average is proxy for live "
            "count; overlapping forecast windows are not independent samples"
            if holdout_start is not None
            else "exploratory evaluation; hourly average is proxy for live count; "
            "not untouched holdout"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--checkpoint", type=int, action="append")
    parser.add_argument("--holdout-start", type=aware_datetime)
    parser.add_argument("--holdout-end", type=aware_datetime)
    args = parser.parse_args()
    for cp in args.checkpoint or (17, 1, 29, 6):
        try:
            result = evaluate(
                args.directory / f"{cp}.json",
                holdout_start=args.holdout_start,
                holdout_end=args.holdout_end,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result), flush=True)
