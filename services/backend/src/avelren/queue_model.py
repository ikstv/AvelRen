"""Queue forecast anchored to a fresh measurement and similar historical changes.

Neighbors match queue size, recent trend and Kyiv clock time. Their future
changes, not absolute historical queue sizes, are added to today's measurement.
This is an experimental nearest-neighbor baseline, not a guarantee of accuracy.
"""

from datetime import datetime, timedelta
from math import ceil, floor
from statistics import median
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
NEIGHBORS = 16
MIN_NEIGHBORS = 4


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    at = (len(ordered) - 1) * fraction
    lower = int(at)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (
        at - lower
    )


def predict_counts(
    history: dict[datetime, float],
    issued_at: datetime,
    current: int,
    targets: list[datetime],
    current_at: datetime | None = None,
) -> dict[datetime, dict]:
    """Use completed history only; no target at/after issue can become a label.

    current_at is the timestamp of the raw live measurement. Offline hourly
    evaluation passes the last complete bucket instead, an acknowledged proxy.
    Ranges are historical neighbor quartiles, not probability guarantees.
    """
    origin = issued_at.replace(minute=0, second=0, microsecond=0)
    past = {
        at: float(value)
        for at, value in history.items()
        if origin - timedelta(weeks=12) <= at < origin
    }
    anchor = current_at or issued_at

    def trend(at: datetime) -> float | None:
        values = [past.get(at - timedelta(hours=i)) for i in range(4)]
        if any(value is None for value in values):
            return None
        return float(median([values[i] - values[i + 1] for i in range(3)]))

    slope = trend(origin - timedelta(hours=1))
    if slope is None:
        return {}
    local_anchor = anchor.astimezone(KYIV)
    neighbors = []
    for at, value in past.items():
        # Use disjoint historical examples, not the unfolding current day.
        if origin - at < timedelta(hours=26):
            continue
        historical_trend = trend(at)
        if historical_trend is None:
            continue
        local = at.astimezone(KYIV)
        hour_distance = abs(local.hour - local_anchor.hour)
        hour_distance = min(hour_distance, 24 - hour_distance)
        distance = (
            abs(value - current) / max(30.0, current * 0.3)
            + abs(historical_trend - slope) / max(10.0, abs(slope))
            + hour_distance / 6.0
            + (local.weekday() != local_anchor.weekday()) * 0.25
        )
        neighbors.append((distance, at, value))
    neighbors.sort()
    result = {}
    for target in targets:
        horizon = (target - anchor).total_seconds() / 3600
        if horizon <= 0 or horizon > 168:
            continue
        lo, hi = floor(horizon), ceil(horizon)
        deltas = []
        for _, at, value in neighbors:
            left = past.get(at + timedelta(hours=lo))
            right = past.get(at + timedelta(hours=hi))
            if left is None or right is None:
                continue
            change = left + (right - left) * (horizon - lo) - value
            deltas.append(change)
            if len(deltas) == NEIGHBORS:
                break
        if len(deltas) < MIN_NEIGHBORS:
            continue
        result[target] = {
            "vehicles_expected": max(0, round(current + median(deltas))),
            "vehicles_low": max(0, round(current + _quantile(deltas, 0.25))),
            "vehicles_high": max(0, round(current + _quantile(deltas, 0.75))),
            "calibration_samples": len(deltas),
        }
    return result
