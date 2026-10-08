"""Мітки подій: справжні прирости, невідомі інтервали та межі."""
from datetime import UTC, datetime, timedelta

import pytest

from tools.surge_experiment.contracts import ObservationRow

T = datetime(2026, 9, 1, tzinfo=UTC)


def series(minutes=220, jump_at=45, amount=20):
    return [ObservationRow(17, T + timedelta(minutes=i), 10 + (amount if i >= jump_at else 0), False)
            for i in range(minutes)]


@pytest.mark.parametrize("distance,expected", [(1800, 1), (1801, 2)])
def test_30minute_merge_boundary(distance, expected):
    from tools.surge_experiment.events import QualifyingWindow, cluster_windows
    windows = [QualifyingWindow(T, T + timedelta(minutes=5), 20),
               QualifyingWindow(T + timedelta(seconds=distance),
                                T + timedelta(seconds=distance + 300), 20)]
    assert len(cluster_windows(windows)) == expected


def test_onset_and_confirmation_are_distinct():
    from tools.surge_experiment.events import build_events
    event, = build_events(series(), T + timedelta(minutes=220))
    assert event.onset_at == T + timedelta(minutes=40)
    assert event.confirmed_at == T + timedelta(minutes=45)
    assert (event.onset_at - (T + timedelta(minutes=43))).total_seconds() == -180
    assert not event.questionable
    assert event.complete


def test_gap_is_unknown_not_zero():
    from tools.surge_experiment.events import HistoryIndex
    from tools.surge_experiment.labels import label_origin, quality_for_origin
    rows = series(2000, 3000)
    rows[450] = ObservationRow(17, T + timedelta(minutes=450, seconds=31), 10, False)
    origin = T + timedelta(minutes=300)
    quality = quality_for_origin(HistoryIndex(rows), origin)
    assert quality.past_valid
    assert not quality.future_known
    assert quality.unknown_intervals
    assert label_origin(origin, [], quality).value is None


def test_positive_survives_unrelated_unknown_future():
    from tools.surge_experiment.events import build_events
    from tools.surge_experiment.labels import WindowQuality, label_origin
    events = build_events(series(220, 135), T + timedelta(minutes=220))
    quality = WindowQuality(True, False, ((T + timedelta(hours=10), T + timedelta(hours=11)),))
    label = label_origin(T + timedelta(minutes=60), events, quality)
    assert label.value == 1
    assert label.event_ids == (events[0].event_id,)


def test_boundary_purges_label_dependency():
    from tools.surge_experiment.labels import Label
    from tools.surge_experiment.splits import purged_origins
    end = T + timedelta(days=1)
    origins = [T, T + timedelta(hours=1)]
    labels = [Label(0, (), end - timedelta(seconds=1), None), Label(1, ("e",), end, None)]
    assert purged_origins(origins, labels, T, end) == [T]


def test_large_jump_overlap_is_not_added():
    from tools.surge_experiment.events import (
        build_events,
        build_large_events,
        overlap_map,
    )
    rows = series(220, 45, 200)
    cutoff = T + timedelta(minutes=220)
    events, big = build_events(rows, cutoff), build_large_events(rows, cutoff)
    assert len(events) == len(big) == 1
    assert overlap_map(events, big) == {big[0].event_id: (events[0].event_id,)}
    assert events[0].event_id != big[0].event_id


def test_open_episode_is_censored():
    from tools.surge_experiment.events import build_events
    from tools.surge_experiment.labels import WindowQuality, label_origin
    event, = build_events(series(220, 135), T + timedelta(minutes=150))
    assert not event.complete
    label = label_origin(T + timedelta(minutes=60), [event], WindowQuality(True, True, ()))
    assert label.value is None
    assert label.reason == "incomplete_or_questionable_event"


def test_missing_completion_data_distinguished_from_temporal_censor():
    from tools.surge_experiment.events import build_events
    rows = series(220, 135)
    temporal, = build_events(rows, T + timedelta(minutes=150))
    missing, = build_events(rows[:150], T + timedelta(minutes=220))
    assert temporal.completion_reason == "right_censored"
    assert missing.completion_reason == "missing_tail"


def test_lag_index_matches_runtime_at_ties_and_gaps():
    from avelren.surge_model import Observation, _lag_index

    from tools.surge_experiment.events import HistoryIndex
    offsets = [0, 60, 120, 180, 240, 270, 330, 390, 450, 510, 570]
    rows = [ObservationRow(17, T + timedelta(seconds=i), 10, False) for i in offsets]
    index = HistoryIndex(rows)
    for j in range(1, len(rows)):
        runtime = [Observation(r.time, r.count, r.paused) for r in rows[:j + 1]]
        assert index.lag(j, 5) == _lag_index(runtime, 5, 90)
    # At 570 the target 270 is exact; at 600 targets 270/330 tie, earlier wins.
    rows[-1] = ObservationRow(17, T + timedelta(seconds=600), 10, False)
    assert HistoryIndex(rows).lag(len(rows) - 1, 5) == 5
