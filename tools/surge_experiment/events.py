"""Епізоди чистого приросту та індекс якості, без моделей і мережі.

Лаги/префікси адаптовано з власного audit episode_metrics.py від 08.10.2026,
SHA256 ec00852875d563329abee327dd866f0b04455dfa4993237e6442f789431af089.
Походження пакета: spec §2. Runtime _lag_index — окремий oracle паритету.
"""
from bisect import bisect_left
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .contracts import ObservationRow


class HistoryIndex:
    """Індекс однієї черги: O(log n) лаг, O(1) перевірка gap."""

    def __init__(self, rows: Sequence[ObservationRow]):
        self.rows = tuple(rows)
        self.times = [r.time.timestamp() for r in rows]
        if any(r.time.tzinfo is None or r.time.utcoffset() is None for r in rows):
            raise ValueError("aware observation time required")
        if any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError("duplicate or unsorted observations")
        if len({r.queue_id for r in rows}) > 1:
            raise ValueError("one queue per history index required")
        self.bad90 = [0] * len(rows)
        self.bad300 = [0] * len(rows)
        self.gaps = []
        for j in range(1, len(rows)):
            gap = self.times[j] - self.times[j - 1]
            self.bad90[j] = self.bad90[j - 1] + (gap > 90)
            self.bad300[j] = self.bad300[j - 1] + (gap > 300)
            if gap > 90:
                self.gaps.append((self.times[j - 1], self.times[j]))
        self._unknown_slots = None

    def nearest(self, target: float, end: int | None = None) -> int | None:
        end = len(self.times) - 1 if end is None else end
        k = bisect_left(self.times, target, 0, end + 1)
        choices = [i for i in (k - 1, k) if 0 <= i <= end]
        return min(choices, key=lambda i: abs(self.times[i] - target)) if choices else None

    def lag(self, j: int, minutes: int, max_gap: int = 90, coverage: bool = False) -> int | None:
        if max_gap not in (90, 300):
            raise ValueError("unsupported gap limit")
        target = self.times[j] - minutes * 60
        i = self.nearest(target, j)
        if i is None or abs(self.times[i] - target) > 30:
            return None
        prefix = self.bad90 if max_gap == 90 else self.bad300
        if prefix[j] != prefix[i] or (coverage and (j - i + 1) / (minutes + 1) < 0.95):
            return None
        return i

    def past_valid(self, j: int) -> bool:
        return (all(self.lag(j, m) is not None for m in (5, 10, 20, 60))
                and all(self.lag(j, m, 300, True) is not None for m in (120, 240)))

    def gap_overlaps(self, start: float, end: float) -> bool:
        return any(a < end and b > start for a, b in self.gaps)

    def unknown_intervals(self, start: datetime, end: datetime) -> tuple[tuple[datetime, datetime], ...]:
        """Номінальні невідомі endpoint-слоти плюс невалідні реальні endpoints."""
        a, b = start.timestamp(), end.timestamp()
        if not self.times:
            return ((start, end),)
        if self._unknown_slots is None:
            slots = []
            target = self.times[0]
            while target <= self.times[-1]:
                j = self.nearest(target)
                if abs(self.times[j] - target) > 30 or self.lag(j, 5) is None:
                    slots.append((target, target + 60))
                target += 60
            # Actual invalid endpoints must also stay unknown even if off the nominal grid.
            slots.extend((t, t + 0.000001) for j, t in enumerate(self.times) if self.lag(j, 5) is None)
            self._unknown_slots = merge_intervals(slots)
        ranges = [(max(a, x), min(b, y)) for x, y in self._unknown_slots if x < b and y > a]
        if a < self.times[0]:
            ranges.append((a, min(b, self.times[0])))
        if b > self.times[-1] + 30:
            ranges.append((max(a, self.times[-1] + 30), b))
        return tuple((datetime.fromtimestamp(x, UTC), datetime.fromtimestamp(y, UTC))
                     for x, y in merge_intervals(ranges) if x < y)


def merge_intervals(intervals):
    result = []
    for start, end in sorted(intervals):
        if not result or start > result[-1][1]:
            result.append((start, end))
        else:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
    return result


@dataclass(frozen=True)
class QualifyingWindow:
    start: datetime
    end: datetime
    net_delta: int


@dataclass(frozen=True)
class Event:
    event_id: str
    queue_id: int
    onset_at: datetime
    confirmed_at: datetime
    last_qualifying_start: datetime
    dependency_end: datetime
    questionable: bool
    complete: bool
    last_confirmed_at: datetime
    kind: str = "net20_5m"
    completion_reason: str | None = None


def cluster_windows(windows: Sequence[QualifyingWindow], *, by_end: bool = False):
    clusters = []
    key = (lambda w: w.end) if by_end else (lambda w: w.start)
    for window in sorted(windows, key=lambda w: (key(w), w.end, w.start)):
        if not clusters or key(window) - key(clusters[-1][-1]) > timedelta(minutes=30):
            clusters.append([window])
        else:
            clusters[-1].append(window)
    return clusters


def _events(index, windows, cutoff, kind="net20_5m"):
    result = []
    for cluster in cluster_windows(windows, by_end=kind == "net200_20m"):
        onset = min(w.start for w in cluster)
        confirmed = min(w.end for w in cluster)
        last_start, last_end = max(w.start for w in cluster), max(w.end for w in cluster)
        dependency = last_start + timedelta(minutes=35) if kind == "net20_5m" else last_end + timedelta(minutes=30)
        queue_id = index.rows[0].queue_id
        questionable = (onset.timestamp() - 1800 < index.times[0]
                        or index.gap_overlaps(onset.timestamp() - 1800, last_end.timestamp()))
        k = index.nearest(dependency.timestamp())
        reason = None
        if dependency >= cutoff:
            reason = "right_censored"
        elif k is None or abs(index.times[k] - dependency.timestamp()) > 30:
            reason = "missing_tail"
        elif index.gap_overlaps(last_end.timestamp(), dependency.timestamp()):
            reason = "unknown_completion"
        result.append(Event(f"{queue_id}:{kind}:{onset.isoformat()}", queue_id, onset, confirmed,
                            last_start, dependency, questionable, reason is None, last_end, kind, reason))
    return result


def build_events(rows: Sequence[ObservationRow], cutoff: datetime) -> list[Event]:
    index = HistoryIndex([r for r in rows if r.time < cutoff])
    windows = []
    for j, row in enumerate(index.rows):
        i = index.lag(j, 5)
        if i is not None and row.count - index.rows[i].count >= 20:
            windows.append(QualifyingWindow(index.rows[i].time, row.time, row.count - index.rows[i].count))
    return _events(index, windows, cutoff)


def build_large_events(rows: Sequence[ObservationRow], cutoff: datetime) -> list[Event]:
    index = HistoryIndex([r for r in rows if r.time < cutoff])
    minimum, windows = deque(), []
    for j, row in enumerate(index.rows):
        if j and index.times[j] - index.times[j - 1] > 90:
            minimum.clear()
        while minimum and index.times[minimum[0]] < index.times[j] - 1200:
            minimum.popleft()
        if minimum and row.count - index.rows[minimum[0]].count >= 200:
            previous = index.rows[minimum[0]]
            windows.append(QualifyingWindow(previous.time, row.time, row.count - previous.count))
        while minimum and index.rows[minimum[-1]].count >= row.count:
            minimum.pop()
        minimum.append(j)
    return _events(index, windows, cutoff, "net200_20m")


def overlap_map(events: Sequence[Event], large_events: Sequence[Event]) -> dict[str, tuple[str, ...]]:
    return {big.event_id: tuple(e.event_id for e in events if e.queue_id == big.queue_id
                               and e.onset_at <= big.last_confirmed_at
                               and e.last_confirmed_at >= big.onset_at) for big in large_events}
