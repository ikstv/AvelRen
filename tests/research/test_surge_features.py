"""Причинні ознаки й внесок події, а не кількості перекритих рядків."""
from datetime import UTC, datetime, timedelta

import pytest

from tools.surge_experiment.contracts import Dataset, ObservationRow
from tools.surge_experiment.labels import Label

T = datetime(2026, 9, 1, tzinfo=UTC)


def constant_rows(minutes=4320, queue_id=17):
    return [ObservationRow(queue_id, T + timedelta(minutes=i), 10, False) for i in range(minutes)]


def test_future_spike_does_not_change_past_features():
    from tools.surge_experiment.features import features_at, fit_scales
    rows = constant_rows(360)
    cutoff = T + timedelta(minutes=360)
    before = Dataset({17: rows}, {})
    after = Dataset({17: rows + [ObservationRow(17, cutoff, 100000, True)]}, {})
    scales = fit_scales(before, cutoff)
    assert fit_scales(after, cutoff) == scales
    origin = T + timedelta(minutes=300)
    assert features_at(before.rows[17], origin, scales) == features_at(after.rows[17], origin, scales)
    assert len(features_at(rows, origin, scales)) == 11


def test_weights_do_not_count_overlapping_origins_as_events():
    from tools.surge_experiment.features import FeatureRow, assign_weights
    pos = Label(1, ("event-a",), T + timedelta(days=2), None)
    neg = Label(0, (), T + timedelta(days=2), None)
    unknown = Label(None, (), T, "gap")
    rows = [FeatureRow(17, T + timedelta(hours=i), (0.0,) * 11, pos, 0) for i in range(3)]
    rows += [FeatureRow(17, T + timedelta(hours=5), (0.0,) * 11, neg, 0),
             FeatureRow(6, T, (0.0,) * 11, neg, 0), FeatureRow(6, T, (0.0,) * 11, unknown, 0)]
    weighted = assign_weights(rows)
    assert len(weighted) == 5
    assert sum(r.weight for r in weighted if r.queue_id == 17) == pytest.approx(0.5)
    assert sum(r.weight for r in weighted if r.label.value == 1) == pytest.approx(0.25)
    assert sum(r.weight for r in weighted) == pytest.approx(1)


def test_zero_event_queue_keeps_known_negatives():
    import json

    from tools.surge_experiment.features import training_rows
    from tools.surge_experiment.manifest import Manifest, protocol_v1
    manifest = Manifest((17,), (), "a" * 40, json.dumps(protocol_v1()))
    rows = training_rows(Dataset({17: constant_rows()}, {}), manifest)
    assert rows
    assert {r.label.value for r in rows} == {0}
    assert sum(r.weight for r in rows) == pytest.approx(1)
    assert all(r.label.dependency_end < T + timedelta(days=3) for r in rows)


def test_constant_scale_is_one():
    from tools.surge_experiment.features import fit_scales
    assert fit_scales(Dataset({17: constant_rows(10)}, {}), T + timedelta(hours=1)) == {17: (10, 1)}


def test_unknown_scale_and_invalid_past_are_unavailable():
    from tools.surge_experiment.features import features_at
    rows = constant_rows(300)
    assert features_at(rows, T + timedelta(minutes=299), {}) is None
    assert features_at(rows[:5], T + timedelta(minutes=4), {17: (10, 1)}) is None


def test_training_scales_and_labels_do_not_read_after_train_end():
    import json

    from tools.surge_experiment.features import training_rows
    from tools.surge_experiment.manifest import Manifest, protocol_v1
    manifest = Manifest((17,), (), "a" * 40, json.dumps(protocol_v1()))
    rows = constant_rows()
    a = training_rows(Dataset({17: rows}, {}), manifest)
    b = training_rows(Dataset({17: rows + [ObservationRow(17, datetime(2026, 9, 19, tzinfo=UTC), 999999, False)]}, {}), manifest)
    assert a == b
