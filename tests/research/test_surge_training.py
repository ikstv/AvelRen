"""Фіксований fit і добір лише за replay selection."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tools.surge_experiment.features import FeatureRow
from tools.surge_experiment.labels import Label
from tools.surge_experiment.manifest import Manifest, protocol_v1

T = datetime(2026, 9, 1, tzinfo=UTC)


def manifest():
    return Manifest((1, 17), (), "a" * 40, json.dumps(protocol_v1()))


def samples():
    return [FeatureRow(q, T + timedelta(hours=i), (float(i % 3),) + (0.,) * 10,
                       Label(int(i % 3 == 2), (f"event:{q}",) if i % 3 == 2 else (),
                             T + timedelta(hours=i + 25), None), 1 / 24)
            for q in (1, 17) for i in range(12)]


def test_training_cutoff_and_unknown_exclusion():
    from tools.surge_experiment.training import fit_candidate
    base = samples()
    unknown = replace(base[0], label=replace(base[0].label, value=None))
    future = replace(base[0], origin=datetime(2026, 9, 25, tzinfo=UTC))
    crossed = replace(base[0], label=replace(base[0].label, dependency_end=datetime(2026, 9, 18, tzinfo=UTC)))
    first = fit_candidate("pooled", base, manifest())
    second = fit_candidate("pooled", base + [unknown, future, crossed], manifest())
    assert first.parameters == second.parameters


def test_single_class_fit_has_explicit_reason():
    from tools.surge_experiment.training import fit_candidate
    result = fit_candidate("pooled", [r for r in samples() if r.label.value == 0], manifest())
    assert result.status == "insufficient_training_classes"


def test_regularization_penalizes_queue_offsets():
    import numpy as np

    from tools.surge_experiment.training import objective
    x = np.zeros((2, 14))
    y, w = np.array([0., 1.]), np.array([0.5, 0.5])
    beta = np.zeros(14)
    base, _ = objective(beta, x, y, w, 0.1, 2)
    beta[0] = 2
    assert objective(beta, x, y, w, 0.1, 2)[0] == base
    beta[0], beta[1] = 0, 2
    feature_penalty = objective(beta, x, y, w, 0.1, 2)[0] - base
    beta[1], beta[-1] = 0, 2
    assert objective(beta, x, y, w, 0.1, 2)[0] - base == pytest.approx(10 * feature_penalty)


def test_repeat_fit_is_deterministic():
    from tools.surge_experiment.training import fit_candidate
    first = fit_candidate("pooled", samples(), manifest())
    second = fit_candidate("pooled", list(reversed(samples())), manifest())
    assert first == second and first.status == "ready"


def test_selection_uses_replay_not_row_accuracy():
    from tools.surge_experiment.training import select_trial
    def trial(key, p, r, accuracy):
        return {"trial_id": key, "precision": p, "overall_recall": r, "fp": 1,
                "threshold": .5, "regularization": .01, "row_accuracy": accuracy,
                "period": "selection", "latency_seconds": 0, "delivery_scenario": "success_no_ack"}
    rows = [trial("poor", .2, .2, 1.), trial("better", .6, .5, .1), trial("undefined", None, 1., 1.)]
    assert select_trial(rows)["trial_id"] == "better"
    with pytest.raises(ValueError, match="selection"):
        select_trial(rows + [trial("leak", 1., 1., 1.) | {"period": "development"}])


def test_local_candidate_excludes_other_queues():
    from tools.surge_experiment.training import fit_candidate
    artifact = fit_candidate("chop_local", samples(), manifest())
    assert artifact.parameters["queue_ids"] == [17]
    assert len(artifact.parameters["coefficients"]) == 12


def test_calendar_smoothing_uses_weighted_train_prior():
    from tools.surge_experiment.features import assign_weights
    from tools.surge_experiment.training import fit_candidate
    rows = assign_weights(samples())
    artifact = fit_candidate("calendar", rows, manifest())
    prior = (sum(r.weight * r.label.value for r in rows) * len(rows) + 1) / (len(rows) + 2)
    assert artifact.parameters["prior"] == pytest.approx(prior)
    row = rows[0]
    local = row.origin.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Kyiv"))
    key = f"{row.queue_id}:{local.weekday()}:{local.hour}"
    assert artifact.parameters["cells"][key] == pytest.approx(10 * prior / (row.weight * len(rows) + 10))


def test_optimizer_failure_has_no_silent_retry(monkeypatch):
    from types import SimpleNamespace

    import numpy as np

    from tools.surge_experiment import training
    calls = []
    def failed(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=False, status=1, nit=1000, x=np.zeros(14))
    monkeypatch.setattr(training, "minimize", failed)
    result = training.fit_candidate("pooled", samples(), manifest())
    assert result.status == "optimizer_not_converged" and len(calls) == 1
