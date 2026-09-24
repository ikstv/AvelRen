"""Walk-forward comparison of queue-forecast baselines on public hourly history.

Reads only AvelRen's public history API. It never contacts the upstream source
or a database. Parameter selection uses the 14 days before the final 14-day
holdout; forecast origins are 06:00 and 12:00 Europe/Kyiv, for the remaining
hours of that local day.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from urllib.request import urlopen
from zoneinfo import ZoneInfo

API = "https://api.bordersignal.pp.ua/api/history/{checkpoint}?hours=2160"
KYIV = ZoneInfo("Europe/Kyiv")
CHECKPOINTS = (17, 1, 29, 6)
RHOS = (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)
MIN_REPEATS = 2


def load_history(checkpoint: int) -> dict[datetime, int]:
    with urlopen(API.format(checkpoint=checkpoint), timeout=30) as response:
        payload = json.load(response)
    return {
        datetime.fromisoformat(point["time"].replace("Z", "+00:00")).astimezone(UTC): int(
            point["avg_vehicles"]
        )
        for point in payload["points"]
        if point.get("avg_vehicles") is not None
    }


def slot(point_time: datetime) -> tuple[int, int]:
    local = point_time.astimezone(KYIV)
    return local.weekday(), local.hour


def prediction_set(
    history: dict[datetime, int], issue_date: date, issue_hour: int, rho: float
) -> list[tuple[datetime, int, int, int, int]]:
    """Return common target, actual, seasonal and hybrid values for one issue."""
    issue = datetime.combine(issue_date, day_time(issue_hour), tzinfo=KYIV).astimezone(UTC)
    past = {at: value for at, value in history.items() if at < issue}
    if not past:
        return []

    training = defaultdict(list)
    window_start = issue - timedelta(weeks=12)
    for at, value in past.items():
        if at >= window_start:
            training[slot(at)].append(value)

    latest_at = max(past)
    current_profile = training.get(slot(latest_at), [])
    if len(current_profile) < MIN_REPEATS:
        return []
    current_residual = past[latest_at] - statistics.median(current_profile)

    predictions = []
    local_date = issue_date
    for hour in range(issue_hour + 1, 24):
        target = datetime.combine(local_date, day_time(hour), tzinfo=KYIV).astimezone(UTC)
        actual = history.get(target)
        seasonal_values = training.get(slot(target), [])
        last_week = history.get(target - timedelta(days=7))
        if actual is None or len(seasonal_values) < MIN_REPEATS or last_week is None:
            continue
        seasonal = int(statistics.median(seasonal_values))
        horizon = int((target - issue).total_seconds() // 3600)
        hybrid = max(0, round(seasonal + (rho**horizon) * current_residual))
        predictions.append((target, actual, seasonal, last_week, hybrid))
    return predictions


def historical_daily_peak_hour(
    history: dict[datetime, int], issue: datetime, issue_date: date, issue_hour: int, mode: bool
) -> int | None:
    """Estimate peak time from prior same-weekday daily peaks, independently of count level."""
    by_date: dict[date, dict[int, int]] = defaultdict(dict)
    for at, value in history.items():
        local = at.astimezone(KYIV)
        if at < issue and at >= issue - timedelta(weeks=12):
            by_date[local.date()][local.hour] = value

    peaks = []
    required = max(3, int((23 - issue_hour) * 0.8))
    for day, values in by_date.items():
        if day >= issue_date or day.weekday() != issue_date.weekday():
            continue
        remaining = [(hour, value) for hour, value in values.items() if issue_hour < hour <= 23]
        if len(remaining) >= required:
            peaks.append(max(remaining, key=lambda pair: (pair[1], -pair[0]))[0])
    if not peaks:
        return None
    if not mode:
        return round(statistics.median(peaks))
    frequencies = {hour: peaks.count(hour) for hour in set(peaks)}
    return max(peaks, key=lambda hour: (frequencies[hour], peaks.index(hour)))


def score(
    history: dict[datetime, int], dates: list[date], rho: float
) -> dict[str, float | int | None]:
    seasonal_errors: list[float] = []
    weekly_errors: list[float] = []
    hybrid_errors: list[float] = []
    seasonal_peak_errors: list[float] = []
    weekly_peak_errors: list[float] = []
    hybrid_peak_errors: list[float] = []
    daily_median_peak_errors: list[float] = []
    daily_mode_peak_errors: list[float] = []
    seasonal_peak_hits = 0
    weekly_peak_hits = 0
    hybrid_peak_hits = 0
    daily_median_peak_hits = 0
    daily_mode_peak_hits = 0
    peak_cases = 0

    for day in dates:
        for issue_hour in (6, 12):
            rows = prediction_set(history, day, issue_hour, rho)
            expected_hours = 23 - issue_hour
            if len(rows) < max(3, int(expected_hours * 0.8)):
                continue

            seasonal_errors.extend(abs(actual - seasonal) for _, actual, seasonal, _, _ in rows)
            weekly_errors.extend(abs(actual - weekly) for _, actual, _, weekly, _ in rows)
            hybrid_errors.extend(abs(actual - hybrid) for _, actual, _, _, hybrid in rows)
            actual_peak = max(rows, key=lambda row: (row[1], -row[0].timestamp()))[0]
            seasonal_peak = max(rows, key=lambda row: (row[2], -row[0].timestamp()))[0]
            weekly_peak = max(rows, key=lambda row: (row[3], -row[0].timestamp()))[0]
            hybrid_peak = max(rows, key=lambda row: (row[4], -row[0].timestamp()))[0]
            seasonal_delta = abs((seasonal_peak - actual_peak).total_seconds()) / 3600
            weekly_delta = abs((weekly_peak - actual_peak).total_seconds()) / 3600
            hybrid_delta = abs((hybrid_peak - actual_peak).total_seconds()) / 3600
            issue = datetime.combine(day, day_time(issue_hour), tzinfo=KYIV).astimezone(UTC)
            actual_peak_hour = actual_peak.astimezone(KYIV).hour
            median_peak_hour = historical_daily_peak_hour(history, issue, day, issue_hour, False)
            mode_peak_hour = historical_daily_peak_hour(history, issue, day, issue_hour, True)
            median_delta = abs(median_peak_hour - actual_peak_hour) if median_peak_hour is not None else None
            mode_delta = abs(mode_peak_hour - actual_peak_hour) if mode_peak_hour is not None else None
            seasonal_peak_errors.append(seasonal_delta)
            weekly_peak_errors.append(weekly_delta)
            hybrid_peak_errors.append(hybrid_delta)
            seasonal_peak_hits += seasonal_delta <= 1
            weekly_peak_hits += weekly_delta <= 1
            hybrid_peak_hits += hybrid_delta <= 1
            peak_cases += 1
            if median_delta is not None:
                daily_median_peak_errors.append(float(median_delta))
                daily_median_peak_hits += median_delta <= 1
            if mode_delta is not None:
                daily_mode_peak_errors.append(float(mode_delta))
                daily_mode_peak_hits += mode_delta <= 1

    def mean(values: list[float]) -> float | None:
        return round(statistics.mean(values), 2) if values else None

    return {
        "hour_points": len(seasonal_errors),
        "peak_cases": peak_cases,
        "seasonal_mae_vehicles": mean(seasonal_errors),
        "last_week_mae_vehicles": mean(weekly_errors),
        "hybrid_mae_vehicles": mean(hybrid_errors),
        "seasonal_peak_mae_hours": mean(seasonal_peak_errors),
        "last_week_peak_mae_hours": mean(weekly_peak_errors),
        "hybrid_peak_mae_hours": mean(hybrid_peak_errors),
        "daily_peak_median_mae_hours": mean(daily_median_peak_errors),
        "daily_peak_mode_mae_hours": mean(daily_mode_peak_errors),
        "seasonal_peak_within_1h_pct": round(100 * seasonal_peak_hits / peak_cases, 1)
        if peak_cases
        else None,
        "last_week_peak_within_1h_pct": round(100 * weekly_peak_hits / peak_cases, 1)
        if peak_cases
        else None,
        "hybrid_peak_within_1h_pct": round(100 * hybrid_peak_hits / peak_cases, 1)
        if peak_cases
        else None,
        "daily_peak_median_within_1h_pct": round(
            100 * daily_median_peak_hits / len(daily_median_peak_errors), 1
        )
        if daily_median_peak_errors
        else None,
        "daily_peak_mode_within_1h_pct": round(
            100 * daily_mode_peak_hits / len(daily_mode_peak_errors), 1
        )
        if daily_mode_peak_errors
        else None,
    }


def main() -> None:
    summaries = []
    for index, checkpoint in enumerate(CHECKPOINTS):
        history = load_history(checkpoint)
        complete_dates = sorted(
            {
                at.astimezone(KYIV).date()
                for at in history
                if at.astimezone(KYIV).hour == 23
            }
        )
        if len(complete_dates) < 35:
            raise SystemExit(f"Checkpoint {checkpoint}: need at least 35 complete local dates")

        holdout_dates = complete_dates[-14:]
        tune_dates = complete_dates[-28:-14]
        tuned: list[tuple[float, float]] = []
        for rho in RHOS:
            tune = score(history, tune_dates, rho)
            mae = tune["hybrid_mae_vehicles"]
            if mae is not None:
                tuned.append((float(mae), rho))
        if not tuned:
            raise SystemExit(f"Checkpoint {checkpoint}: no valid tuning cases")

        selected_rho = min(tuned)[1]
        results = score(history, holdout_dates, selected_rho)
        summaries.append(
            {
                "checkpoint_id": checkpoint,
                "points": len(history),
                "first_utc": min(history).isoformat(),
                "last_utc": max(history).isoformat(),
                "tuning_dates": [tune_dates[0].isoformat(), tune_dates[-1].isoformat()],
                "holdout_dates": [holdout_dates[0].isoformat(), holdout_dates[-1].isoformat()],
                "selected_rho_for_vehicle_mae": selected_rho,
                **results,
            }
        )
        if index < len(CHECKPOINTS) - 1:
            time.sleep(1)

    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
