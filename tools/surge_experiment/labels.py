"""Тризначні майбутні мітки; позитивна подія не вимагає заповнення прогалин нулями."""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from .events import Event, HistoryIndex


@dataclass(frozen=True)
class WindowQuality:
    past_valid: bool
    future_known: bool
    unknown_intervals: tuple[tuple[datetime, datetime], ...]


@dataclass(frozen=True)
class Label:
    value: int | None
    event_ids: tuple[str, ...]
    dependency_end: datetime
    reason: str | None


def quality_for_origin(index: HistoryIndex, origin: datetime) -> WindowQuality:
    j = bisect_right(index.times, origin.timestamp()) - 1
    past = j >= 0 and origin.timestamp() - index.times[j] <= 180 and index.past_valid(j)
    unknown = index.unknown_intervals(origin + timedelta(minutes=65), origin + timedelta(minutes=1445, microseconds=1))
    return WindowQuality(past, not unknown, unknown)


def label_origin(origin: datetime, events: list[Event], quality: WindowQuality) -> Label:
    end = origin + timedelta(minutes=1445)
    if not quality.past_valid:
        return Label(None, (), end, "insufficient_history")
    reachable = sorted((e for e in events if origin + timedelta(hours=1) <= e.onset_at <= origin + timedelta(hours=24)),
                       key=lambda e: (e.onset_at, e.event_id))
    clean = [e for e in reachable if not e.questionable and e.complete]
    if clean:
        return Label(1, tuple(e.event_id for e in clean), max(e.dependency_end for e in clean), None)
    if reachable:
        return Label(None, (), max(end, *(e.dependency_end for e in reachable)), "incomplete_or_questionable_event")
    return Label(0 if quality.future_known else None, (), end, None if quality.future_known else "unknown_future")
