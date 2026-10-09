"""Ознаки, які були доступні до рішення; ваги за подіями й днями."""
import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from .contracts import Dataset, ObservationRow
from .data import timestamp
from .events import HistoryIndex, build_events
from .labels import Label, label_origin, quality_for_origin
from .manifest import Manifest

KYIV = ZoneInfo("Europe/Kyiv")


@dataclass(frozen=True)
class FeatureRow:
    queue_id: int
    origin: datetime
    values: tuple[float, ...]
    label: Label
    weight: float


def _quantile(values, fraction):
    position = (len(values) - 1) * fraction
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def fit_scales(dataset: Dataset, train_end: datetime) -> dict[int, tuple[float, float]]:
    result = {}
    for queue_id, rows in dataset.rows.items():
        counts = sorted(row.count for row in rows if row.time < train_end)
        if counts:
            result[queue_id] = (_quantile(counts, 0.5), max(1, _quantile(counts, 0.75) - _quantile(counts, 0.25)))
    return result


def features_at(rows: Sequence[ObservationRow] | HistoryIndex, origin: datetime,
                scales: dict[int, tuple[float, float]]) -> tuple[float, ...] | None:
    index = rows if isinstance(rows, HistoryIndex) else HistoryIndex(rows)
    j = bisect_right(index.times, origin.timestamp()) - 1
    if j < 0 or origin.timestamp() - index.times[j] > 180 or not index.past_valid(j):
        return None
    current = index.rows[j]
    if current.queue_id not in scales:
        return None
    center, scale = scales[current.queue_id]
    if not math.isfinite(center) or not math.isfinite(scale) or scale < 1:
        raise ValueError("invalid training scale")
    d5, d10, d20, d60 = (current.count - index.rows[index.lag(j, m)].count for m in (5, 10, 20, 60))
    local = current.time.astimezone(KYIV)
    phase = local.hour * 60 + local.minute
    return ((current.count - center) / scale, d5 / scale, d10 / scale, d20 / scale, d60 / scale,
            (d5 - d10 / 2) / scale, float(current.paused),
            math.sin(2 * math.pi * phase / 1440), math.cos(2 * math.pi * phase / 1440),
            math.sin(2 * math.pi * local.weekday() / 7), math.cos(2 * math.pi * local.weekday() / 7))


def hourly_origins(index: HistoryIndex, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Перший придатний observation origin і хвилинний tick кожної UTC-ідентичної місцевої години."""
    if not index.times:
        return []
    clock = math.ceil(max(start.timestamp(), index.times[0]) / 60) * 60
    stop = min(end.timestamp(), index.times[-1] + 181)
    used, result = set(), []
    while clock < stop:
        now = datetime.fromtimestamp(clock, UTC)
        hour = now.astimezone(KYIV).replace(minute=0, second=0, microsecond=0).astimezone(UTC)
        j = bisect_right(index.times, clock) - 1
        if (j >= 0 and hour not in used and index.times[j] >= hour.timestamp()
                and clock - index.times[j] <= 180 and index.past_valid(j)):
            used.add(hour)
            result.append((index.rows[j].time, now))
        clock += 60
    return result


def assign_weights(rows: list[FeatureRow]) -> list[FeatureRow]:
    known = [r for r in rows if r.label.value is not None]
    if not known:
        return []

    def group(row):
        return (row.queue_id, "event", row.label.event_ids[0]) if row.label.value == 1 else (
            row.queue_id, "negative_day", row.origin.astimezone(KYIV).date())

    sizes = Counter(group(r) for r in known)
    queue_groups = Counter(key[0] for key in sizes)
    queue_count = len(queue_groups)
    return [replace(r, weight=1 / sizes[group(r)] / queue_groups[r.queue_id] / queue_count) for r in known]


def training_rows(dataset: Dataset, manifest: Manifest) -> list[FeatureRow]:
    periods = manifest.settings["periods"]
    start, end = timestamp(periods["train_start"]), timestamp(periods["train_end"])
    train = Dataset({q: tuple(r for r in rows if start <= r.time < end) for q, rows in dataset.rows.items()},
                    dataset.source_hashes)
    scales = fit_scales(train, end)
    examples = []
    for queue_id, rows in train.rows.items():
        index = HistoryIndex(rows)
        events = build_events(rows, end)
        for origin, _ in hourly_origins(index, start, end):
            values = features_at(index, origin, scales)
            label = label_origin(origin, events, quality_for_origin(index, origin))
            if values is not None and label.value is not None and label.dependency_end < end:
                examples.append(FeatureRow(queue_id, origin, values, label, 0))
    return assign_weights(sorted(examples, key=lambda row: (row.origin, row.queue_id)))
