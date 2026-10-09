"""Синтетичні приклади знаменників, зіставлення й часових меж."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tools.surge_experiment.events import Event
from tools.surge_experiment.replay import ReplayResult

T = datetime(2026, 9, 18, tzinfo=UTC)


def event(key="e1", onset=None, **kwargs):
    start = onset or T + timedelta(hours=30)
    return replace(Event(key, 17, start, start + timedelta(minutes=5), start,
                         start + timedelta(minutes=35), False, True, start + timedelta(minutes=5)), **kwargs)


def alert(key="a1", when=None, **kwargs):
    now = when or T + timedelta(hours=12)
    return {"alert_id": key, "queue_id": 17, "kind": "surge_forecast", "alert_created_at": now,
            "window_start": now + timedelta(hours=1), "window_end": now + timedelta(hours=24),
            "closed_at": None, **kwargs}


def evaluate(alerts=(), events=(), unknown=(), available=True):
    from tools.surge_experiment.metrics import EvaluationContext, evaluate_alerts
    context = EvaluationContext(17, T, T + timedelta(days=7), tuple(unknown), 5 * 86400)
    result = ReplayResult([], list(alerts), [{"queue_id": 17, "start": T, "end": T + timedelta(days=7),
                                            "past_valid": available, "fresh": available, "status": "available"}])
    return evaluate_alerts(result, list(events), None, context=context)


def test_one_alert_matches_only_one_event():
    m = evaluate([alert()], [event(), event("e2", T + timedelta(hours=31))])
    assert m["tp_alerts"] == m["matched_events"] == 1 and m["fn_events"] == 1


def test_three_initial_alerts_one_event_gives_two_fp():
    m = evaluate([alert(f"a{i}", T + timedelta(hours=12 + i)) for i in range(3)], [event()])
    assert (m["tp_alerts"], m["fp_alerts"], m["precision"]) == (1, 2, 1 / 3)
    assert m["fp_reasons"]["duplicate_unmatched"] == 2


def test_cancel_does_not_remove_false_alert():
    m = evaluate([alert(closed_at=T + timedelta(hours=13))])
    assert m["fp_alerts"] == 1


def test_no_events_recall_null():
    m = evaluate([alert()])
    assert m["overall_recall"] is None and m["recall_reason"] == "no_evaluable_events"


def test_no_alerts_precision_null():
    m = evaluate(events=[event()])
    assert m["precision"] is None and m["fn_events"] == 1


def test_unknown_horizon_not_fp():
    m = evaluate([alert()], unknown=[(T + timedelta(hours=20), T + timedelta(hours=21))])
    assert m["fp_alerts"] == 0 and m["unassessable_alerts"] == 1


def test_positive_match_with_partial_unknown_is_tp():
    unknown = [(T + timedelta(hours=20), T + timedelta(hours=21))]
    m = evaluate([alert(), alert("a2")], [event()], unknown)
    assert m["tp_alerts"] == 1 and m["unassessable_alerts"] == 1 and m["fp_alerts"] == 0


def test_end_censor_not_fn():
    m = evaluate(events=[event(complete=False, completion_reason="right_censored")])
    assert m["fn_events"] == 0 and m["excluded_events"]["right_censored"] == 1


def test_matching_ties_ignore_input_order():
    alerts, events = [alert("b"), alert("a")], [event("z"), event("c")]
    assert evaluate(alerts, events)["matches"] == evaluate(alerts[::-1], events[::-1])["matches"]
    assert evaluate(alerts, events)["matches"][0]["event_id"] == "c"


def test_boundary_differs_from_real_gap():
    m = evaluate(events=[event(), event("edge", T + timedelta(hours=23))], available=False)
    assert m["fn_events"] == m["events_without_history"] == 1
    assert m["excluded_events"]["temporal_edge"] == 1


def test_separate_precision_and_recall_cohorts():
    m = evaluate([alert(when=T)], [event(onset=T + timedelta(hours=2))])
    assert m["tp_alerts"] == 1 and m["matched_events"] == 0 and m["overall_recall"] is None


def test_exact_phase_cohorts():
    from tools.surge_experiment.data import timestamp
    from tools.surge_experiment.metrics import phase_cohorts
    c = phase_cohorts(timestamp("2026-09-18T00:00:00+03:00"), timestamp("2026-09-25T00:00:00+03:00"))
    assert c["alert_end"] == timestamp("2026-09-23T23:25:00+03:00")
    assert c["event_start"] == timestamp("2026-09-19T00:00:00+03:00")
    assert c["event_end"] == timestamp("2026-09-24T00:25:00+03:00")


def test_unknown_overlap_union():
    from tools.surge_experiment.metrics import union_seconds
    assert union_seconds([(T, T + timedelta(minutes=3)), (T + timedelta(minutes=1), T + timedelta(minutes=5))]) == 300


def test_ci_short_or_degenerate_null():
    from tools.surge_experiment.metrics import block_ci
    assert block_ci([(1, 2)] * 7)["reason"] == "fewer_than_28_days"
    assert block_ci([(1, 1)] * 28)["reason"] == "degenerate_distribution"
    assert block_ci([(0, 0)] * 28)["reason"] == "insufficient_valid_resamples"


def test_unmet_target_stops_without_extra_fit():
    from tools.surge_experiment.metrics import stop_status
    assert stop_status(.98, .99) == "criterion_not_met"
    assert stop_status(None, 1.) == "insufficient_evidence"
    assert stop_status(1., 1.) == "eligible_for_future_test_not_quality_confirmation"


def test_assessable_rate_denominator_and_original_window():
    m = evaluate([alert(window_end=T + timedelta(hours=29))], [event()])
    assert m["tp_alerts"] == 0 and m["fp_per_30_days"] == pytest.approx(6.)


def test_questionable_label_is_neither_false_positive_nor_false_negative():
    m = evaluate([alert()], [event(questionable=True)])
    assert m["fp_alerts"] == m["fn_events"] == 0
    assert m["unassessable_alerts"] == m["excluded_events"]["questionable"] == 1


def test_available_event_requires_real_origin_and_original_horizon():
    from tools.surge_experiment.metrics import EvaluationContext, evaluate_alerts
    context = EvaluationContext(17, T, T + timedelta(days=7), (), 5 * 86400)
    value = event(onset=T + timedelta(hours=30, minutes=30))
    decision = {"queue_id": 17, "now": T + timedelta(hours=6),
                "observed_at": T + timedelta(hours=6), "prediction_attempt": True,
                "forecast_available": True, "past_valid": True, "fresh": True,
                "window_start": T + timedelta(hours=7), "window_end": T + timedelta(hours=30)}
    result = ReplayResult([decision], [], [{"queue_id": 17, "start": T + timedelta(hours=6),
        "end": T + timedelta(hours=6, minutes=31), "past_valid": True,
        "fresh": True, "status": "ready"}])
    metrics = evaluate_alerts(result, [value], None, context=context)
    assert metrics["available_events"] == 0 and metrics["events_without_history"] == 1
    decision["window_end"] += timedelta(minutes=30)
    decision["observed_at"] += timedelta(minutes=30)
    decision["now"] += timedelta(minutes=30)
    assert evaluate_alerts(result, [value], None, context=context)["available_events"] == 1


def test_report_aggregates_unknown_origins_and_delivery_without_double_counting():
    from tools.surge_experiment.metrics import EvaluationContext, evaluate_alerts
    context = EvaluationContext(17, T, T + timedelta(days=7),
        ((T + timedelta(hours=20), T + timedelta(hours=21)),), 5 * 86400)
    decision = {"queue_id": 17, "now": T + timedelta(hours=12),
        "observed_at": T + timedelta(hours=12), "prediction_attempt": True,
        "forecast_available": False, "past_valid": False, "fresh": True,
        "window_start": T + timedelta(hours=13), "window_end": T + timedelta(hours=36)}
    result = ReplayResult([decision], [alert()], [],
        [{"alert_id": "a1", "attempt_id": "a1:1", "ordinal": 1, "attempt_count": 2,
          "accepted_at": T + timedelta(hours=12)},
         {"alert_id": "a1", "attempt_id": "a1:2", "ordinal": 2, "attempt_count": 1,
          "accepted_at": T + timedelta(hours=12, minutes=5)}],
        [{"queue_id": 17, "alert_id": "a1", "now": T + timedelta(hours=13)}])
    metrics = evaluate_alerts(result, [], None, context=context)
    assert metrics["unknown_seconds"] == 3600
    assert metrics["origin_counts"] == {"attempted": 1, "past_unavailable": 1,
        "forecast_available": 0, "unknown_future": 1, "questionable_future": 0,
        "affected_union": 1, "assessable_future": 0}
    assert metrics["delivery_counts"]["initial_attempts"] == 1
    assert metrics["delivery_counts"]["reminders"] == 1
    assert metrics["delivery_counts"]["retries"] == 1
    assert metrics["delivery_counts"]["cancels"] == 1
