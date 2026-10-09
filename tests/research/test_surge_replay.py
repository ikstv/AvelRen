"""Replay перевіряє рішення годинника, видимість даних і збереження стану."""
import json
from datetime import UTC, datetime, timedelta

from tools.surge_experiment.contracts import Dataset, ObservationRow
from tools.surge_experiment.manifest import Manifest, protocol_v1

T = datetime(2026, 9, 18, tzinfo=UTC)


def observations(start=T, minutes=70, queue_id=17):
    return [ObservationRow(queue_id, start + timedelta(minutes=i), 10, False) for i in range(-250, minutes)]


def manifest(start=T, minutes=3, enable=None, ids=(17,)):
    config = protocol_v1()
    config["replay"]["start"] = start.isoformat()
    config["replay"]["forecast_enabled_from"] = (enable or start).isoformat()
    config["periods"]["development_end"] = (start + timedelta(minutes=minutes)).isoformat()
    return Manifest(ids, (), "a" * 40, json.dumps(config))


class FixedCandidate:
    supported_ids = None

    def __init__(self, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    def score(self, queue_id, rows, origin):
        from tools.surge_experiment.replay import ScoreResult
        self.calls.append((queue_id, origin, tuple(rows)))
        if self.fail_first and len(self.calls) == 1:
            return ScoreResult(None, 0.5, "unavailable", "insufficient_history")
        return ScoreResult(0.9, 0.5, "available", None)


def test_frozen_other_34_ids_not_applicable_without_predict_call(monkeypatch):
    from tools.surge_experiment import frozen
    from tools.surge_experiment.replay import replay
    def forbidden(*args):
        raise AssertionError("unsupported model invocation")
    monkeypatch.setattr(frozen, "predict_surge", forbidden)
    candidate = frozen.FrozenCandidate()
    score = candidate.score(14, observations(queue_id=14), T)
    assert score.status == "not_applicable" and score.score is None
    result = replay(Dataset({14: observations(queue_id=14)}, {}), candidate, manifest(ids=(14,)), 0)
    assert not result.alerts
    assert {r["status"] for r in result.availability} == {"not_applicable"}


def test_retry_after_new_observation_same_hour():
    from tools.surge_experiment.replay import replay
    candidate = FixedCandidate(fail_first=True)
    result = replay(Dataset({17: observations()}, {}), candidate, manifest(), 0)
    assert [call[1] for call in candidate.calls] == [T, T + timedelta(minutes=1)]
    assert len(result.alerts) == 1
    assert result.alerts[0]["alert_created_at"] == T + timedelta(minutes=1)


def test_missing_unsupported_queue_still_not_applicable():
    from tools.surge_experiment.frozen import FrozenCandidate
    from tools.surge_experiment.replay import replay
    result = replay(Dataset({}, {}), FrozenCandidate(), manifest(ids=(14,)), 0)
    assert result.availability[0]["status"] == "not_applicable"


def test_success_once_per_hour():
    from tools.surge_experiment.replay import replay
    candidate = FixedCandidate()
    replay(Dataset({17: observations()}, {}), candidate, manifest(minutes=65), 0)
    assert [call[1] for call in candidate.calls] == [T, T + timedelta(hours=1)]


def test_ticks_without_data_expire_state():
    from tools.surge_experiment.replay import replay
    result = replay(Dataset({17: observations(minutes=2)}, {}), FixedCandidate(), manifest(minutes=8), 0)
    assert result.alerts[0]["closed_at"] == T + timedelta(minutes=5)
    assert result.alerts[0]["close_reason"] == "stale"
    assert result.availability[-1]["status"] == "unavailable"


def test_dst_repeated_hour_distinct_utc():
    from tools.surge_experiment.replay import replay
    start = datetime(2026, 10, 25, tzinfo=UTC)
    candidate = FixedCandidate()
    replay(Dataset({17: observations(start=start)}, {}), candidate, manifest(start=start, minutes=65), 0)
    assert [call[1] for call in candidate.calls] == [start, start + timedelta(hours=1)]


def test_future_rows_invisible_before_available_at():
    from tools.surge_experiment.replay import replay
    candidate = FixedCandidate(fail_first=True)
    replay(Dataset({17: observations()}, {}), candidate, manifest(minutes=4), 60)
    assert [call[1] for call in candidate.calls] == [T, T + timedelta(minutes=1)]
    assert all(max(r.time for r in rows) == origin for _, origin, rows in candidate.calls)


def test_model_never_runs_before_train_end():
    from tools.surge_experiment.replay import replay
    candidate = FixedCandidate()
    replay(Dataset({17: observations()}, {}), candidate, manifest(minutes=5, enable=T + timedelta(minutes=2)), 0)
    assert [call[1] for call in candidate.calls] == [T + timedelta(minutes=2)]


def test_carry_in_preserves_state_and_ack():
    from tools.surge_experiment.events import HistoryIndex
    from tools.surge_experiment.replay import ReplayEngine
    engine = ReplayEngine(17, FixedCandidate(), T)
    index = HistoryIndex(observations(minutes=125))
    engine.step(index, T + timedelta(minutes=59), 0)
    original = dict(engine.alerts[0])
    engine.acknowledge(original["alert_id"])
    engine.step(index, T + timedelta(minutes=60), 0)
    assert len(engine.alerts) == 1
    assert engine.alerts[0]["window_end"] == original["window_end"]
    assert original["alert_id"] in engine.acknowledged
    assert engine.state.forecast.updated_at == T + timedelta(minutes=60)


def test_delivery_scenarios_count_reminders_separately():
    from tools.surge_experiment.replay import replay
    data = Dataset({17: observations()}, {})
    normal = replay(data, FixedCandidate(), manifest(minutes=15), 0)
    acked = replay(data, FixedCandidate(), manifest(minutes=15), 0, delivery_scenario="ack_first")
    assert len(normal.alerts) == len(acked.alerts) == 1
    assert [a["ordinal"] for a in normal.delivery_attempts] == [1, 2, 3]
    assert len(acked.delivery_attempts) == len(acked.cancels) == 1
    assert sum((a["end"] - a["start"]).total_seconds() / 60 * a.get("acknowledged_active", 0)
               for a in acked.availability) == 14
    valid_origins = [r for r in normal.decisions if r.get("forecast_available")]
    assert valid_origins and all(r["window_end"] == r["observed_at"] + timedelta(hours=24)
                                for r in valid_origins)


def test_quality_respects_database_history_lower_bound():
    from tools.surge_experiment.events import HistoryIndex
    from tools.surge_experiment.frozen import FrozenCandidate
    from tools.surge_experiment.replay import ReplayEngine
    observed = T - timedelta(minutes=3)
    rows = [ObservationRow(17, observed - timedelta(minutes=240, seconds=30), 10, False)]
    rows += [ObservationRow(17, observed - timedelta(minutes=i), 10, False) for i in range(239, -1, -1)]
    index = HistoryIndex(rows)
    assert index.past_valid(len(rows) - 1)
    engine = ReplayEngine(17, FrozenCandidate(), T)
    engine.step(index, T, 0)
    assert engine.availability[-1]["past_valid"] is False
