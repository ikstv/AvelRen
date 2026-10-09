"""Оцінка початкових попереджень і незалежних епізодів, невідоме лишається невідомим."""
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .events import HistoryIndex, merge_intervals
from .features import KYIV


def phase_cohorts(start, end):
    return {"alert_start": start, "alert_end": end - timedelta(hours=24, minutes=35),
            "event_start": start + timedelta(hours=24), "event_end": end - timedelta(hours=23, minutes=35),
            "label_cutoff": end}


def union_seconds(intervals):
    return sum(b - a for a, b in merge_intervals([(a.timestamp(), b.timestamp()) for a, b in intervals]))


@dataclass(frozen=True)
class EvaluationContext:
    queue_id: int
    start: datetime
    end: datetime
    unknown_endpoints: tuple
    assessable_seconds: float
    uncertain_events: tuple = ()

    def future_known(self, window_start, window_end):
        lo, hi = window_start + timedelta(minutes=5), window_end + timedelta(minutes=5)
        return (not any(a <= hi and b > lo for a, b in self.unknown_endpoints)
                and not any(window_start <= e.onset_at <= window_end for e in self.uncertain_events))


def evaluation_context(queue_id, rows, events, start, end):
    index = HistoryIndex([r for r in rows if r.time < end])
    unknown = index.unknown_intervals(start, end)
    uncertain = tuple(e for e in events if e.queue_id == queue_id and
                      (e.questionable or not e.complete or e.dependency_end >= end))
    context = EvaluationContext(queue_id, start, end, unknown, 0, uncertain)
    cohorts = phase_cohorts(start, end)
    intervals = []
    clock = math.ceil(start.timestamp() / 60) * 60
    while clock < cohorts["alert_end"].timestamp():
        now = datetime.fromtimestamp(clock, UTC)
        if context.future_known(now + timedelta(hours=1), now + timedelta(hours=24)):
            intervals.append((now, min(now + timedelta(minutes=1), cohorts["alert_end"])))
        clock += 60
    return EvaluationContext(queue_id, start, end, unknown, union_seconds(intervals), uncertain)


def stop_status(precision, recall):
    if precision is None or recall is None:
        return "insufficient_evidence"
    return "criterion_not_met" if min(precision, recall) < .99 else "eligible_for_future_test_not_quality_confirmation"


def block_ci(daily):
    """Однаковий seed/кількість днів дає парні індекси для всіх кандидатів/черг."""
    import numpy as np
    result = {"interval": None, "reason": None, "method": "moving_block_percentile_7_days",
              "assumption": "limited_temporal_dependence", "valid_resamples": 0}
    if len(daily) < 28:
        return result | {"reason": "fewer_than_28_days"}
    values = np.asarray(daily, dtype=float)
    if values.shape != (len(daily), 2) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("invalid daily contributions")
    rng = np.random.default_rng(20261009)
    starts = rng.integers(0, len(daily) - 6, size=(2000, math.ceil(len(daily) / 7)))
    indices = (starts[:, :, None] + np.arange(7)).reshape(2000, -1)[:, :len(daily)]
    totals = values[indices].sum(axis=1)
    valid = totals[:, 1] > 0
    count = int(valid.sum())
    if count < 1800:
        return result | {"reason": "insufficient_valid_resamples", "valid_resamples": count}
    ratios = totals[valid, 0] / totals[valid, 1]
    if ratios.min() == ratios.max():
        return result | {"reason": "degenerate_distribution", "valid_resamples": count}
    return result | {"interval": np.quantile(ratios, [.025, .975]).tolist(), "valid_resamples": count}


def exact_diagnostic(successes, total):
    # API: scipy.stats.BinomTestResult.proportion_ci(method="exact"), docs inspected 09.10.2026.
    from scipy.stats import binomtest
    if not total:
        return {"interval": None, "reason": "zero_denominator", "assumption": "independent_trials"}
    ci = binomtest(successes, total).proportion_ci(confidence_level=.95, method="exact")
    return {"interval": [float(ci.low), float(ci.high)], "reason": None, "assumption": "independent_trials"}


def evaluate_alerts(result, events, manifest, *, context, include_trace=True):
    c = phase_cohorts(context.start, context.end)
    events = sorted((e for e in events if e.queue_id == context.queue_id), key=lambda e: (e.onset_at, e.event_id))
    clean = [e for e in events if not e.questionable and e.complete and e.dependency_end < context.end]
    eligible = [e for e in clean if c["event_start"] <= e.onset_at < c["event_end"]]
    excluded, event_rows = Counter(), []
    for e in events:
        reason = None
        if e.dependency_end < context.start:
            reason = "prior_history"
        elif e.onset_at < context.start:
            reason = "carry_in"
        elif e.questionable:
            reason = "questionable"
        elif not e.complete:
            reason = e.completion_reason or "incomplete"
        elif e.dependency_end >= context.end:
            reason = "right_censored"
        elif e not in eligible:
            reason = "temporal_edge"
        if reason:
            excluded[reason] += 1
        event_rows.append({"event_id": e.event_id, "onset_at": e.onset_at, "confirmed_at": e.confirmed_at,
                           "reason": reason, "dependency_end": e.dependency_end})
    alerts = sorted((a for a in result.alerts if a["queue_id"] == context.queue_id and a["kind"] == "surge_forecast"),
                    key=lambda a: (a["alert_created_at"], a["queue_id"], a["alert_id"]))
    if len({a["alert_id"] for a in alerts}) != len(alerts):
        raise ValueError("duplicate initial alert ID")
    used, matches, outcomes, fp_reasons = set(), [], [], Counter()
    for a in alerts:
        now = a["alert_created_at"]
        outcome = {"alert_id": a["alert_id"], "created_at": now}
        if not c["alert_start"] <= now < c["alert_end"]:
            outcomes.append(outcome | {"outcome": "edge", "reason": "carry_in" if now < context.start else "temporal_edge"})
            continue
        lo, hi = max(now + timedelta(hours=1), a["window_start"]), min(now + timedelta(hours=24), a["window_end"])
        reachable = [e for e in clean if lo <= e.onset_at <= hi]
        match = next((e for e in reachable if e.event_id not in used), None)
        if match is not None:
            used.add(match.event_id)
            matches.append({"alert_id": a["alert_id"], "event_id": match.event_id,
                            "lead_seconds": (match.onset_at - now).total_seconds()})
            outcomes.append(outcome | {"outcome": "tp", "reason": None})
        elif context.future_known(lo, hi) and not any(lo <= e.onset_at <= hi and e not in clean for e in events):
            reason = "duplicate_unmatched" if reachable else "no_event"
            fp_reasons[reason] += 1
            outcomes.append(outcome | {"outcome": "fp", "reason": reason})
        else:
            outcomes.append(outcome | {"outcome": "unassessable", "reason": "unknown_future"})
    outcomes_count = Counter(o["outcome"] for o in outcomes)
    tp, fp = outcomes_count["tp"], outcomes_count["fp"]
    available = []
    attempted = [r for r in result.decisions if r["queue_id"] == context.queue_id
                 and r.get("prediction_attempt") and context.start <= r["now"] < context.end]
    for e in eligible:
        if any(r.get("forecast_available") and r.get("past_valid") and r.get("fresh")
               and r["now"] + timedelta(hours=1) <= e.onset_at <= r["now"] + timedelta(hours=24)
               and r["window_start"] <= e.onset_at <= r["window_end"] for r in attempted):
            available.append(e)
    origins = [r for r in attempted if c["alert_start"] <= r["now"] < c["alert_end"]]
    origin_sets = {key: set() for key in ("past_unavailable", "unknown_future", "questionable_future")}
    forecast_available = set()
    for r in origins:
        key = (r["observed_at"], r["now"])
        if not r.get("past_valid") or not r.get("fresh"):
            origin_sets["past_unavailable"].add(key)
        if r.get("forecast_available") and r.get("past_valid") and r.get("fresh"):
            forecast_available.add(key)
        lo, hi = r["window_start"], r["window_end"]
        if any(a <= hi + timedelta(minutes=5) and b > lo + timedelta(minutes=5)
               for a, b in context.unknown_endpoints):
            origin_sets["unknown_future"].add(key)
        if any(lo <= e.onset_at <= hi for e in context.uncertain_events):
            origin_sets["questionable_future"].add(key)
    affected = origin_sets["unknown_future"] | origin_sets["questionable_future"]
    all_origins = {(r["observed_at"], r["now"]) for r in origins}
    origin_counts = {"attempted": len(all_origins),
                     "past_unavailable": len(origin_sets["past_unavailable"]),
                     "forecast_available": len(forecast_available),
                     "unknown_future": len(origin_sets["unknown_future"]),
                     "questionable_future": len(origin_sets["questionable_future"]),
                     "affected_union": len(affected),
                     "assessable_future": len(all_origins - affected)}
    matched = sum(e.event_id in used for e in eligible)
    precision, recall = tp / (tp + fp) if tp + fp else None, matched / len(eligible) if eligible else None
    day = context.start.astimezone(KYIV).date()
    last = context.end.astimezone(KYIV).date()
    daily = {}
    while day < last:
        daily[day.isoformat()] = [0, 0, 0, 0]
        day += timedelta(days=1)
    for o in outcomes:
        key = o["created_at"].astimezone(KYIV).date().isoformat()
        if key in daily:
            daily[key][0] += o["outcome"] == "tp"
            daily[key][1] += o["outcome"] in ("tp", "fp")
    for e in eligible:
        key = e.onset_at.astimezone(KYIV).date().isoformat()
        if key in daily:
            daily[key][2] += e.event_id in used
            daily[key][3] += 1
    availability = Counter()
    ready_seconds = fresh_seconds = ack_ticks = disabled_ticks = 0
    for r in result.availability:
        if r["queue_id"] == context.queue_id:
            seconds = max(0, (min(context.end, r["end"]) - max(context.start, r["start"])).total_seconds())
            availability[r["status"]] += seconds
            ready_seconds += seconds * (r["past_valid"] and r["fresh"])
            fresh_seconds += seconds * r["fresh"]
            ack_ticks += seconds / 60 * r.get("acknowledged_active", 0)
            disabled_ticks += seconds / 60 * r.get("disabled_active", 0)
    queue_alert_ids = {a["alert_id"] for a in result.alerts if a["queue_id"] == context.queue_id}
    delivery = [a for a in result.delivery_attempts
                if (a.get("queue_id") == context.queue_id or a["alert_id"] in queue_alert_ids)
                and context.start <= a.get("created_at", context.start) < context.end]
    cancels = [r for r in result.cancels if r["queue_id"] == context.queue_id
               and context.start <= r["now"] < context.end]
    delivery_counts = {"initial_alerts": sum(context.start <= a["alert_created_at"] < context.end
                       for a in result.alerts if a["queue_id"] == context.queue_id),
                       "initial_attempts": sum(a["ordinal"] == 1 for a in delivery),
                       "reminders": sum(a["ordinal"] > 1 for a in delivery),
                       "retries": sum(a["attempt_count"] - 1 for a in delivery),
                       "accepted_attempts": sum(a["accepted_at"] is not None for a in delivery),
                       "cancels": len(cancels), "suppressed_ack_ticks": int(ack_ticks),
                       "suppressed_disabled_ticks": int(disabled_ticks)}
    trace = {} if not include_trace else {
        "unknown_intervals": context.unknown_endpoints,
        "forecast_origins": origins,
        "affected_origin_sets": {key: sorted(value) for key, value in
                                  (origin_sets | {"affected_union": affected}).items()}}
    leads = sorted(m["lead_seconds"] for m in matches)
    return {"queue_id": context.queue_id, "status": "evaluated", "cohorts": c,
            "tp_alerts": tp, "fp_alerts": fp, "fp": fp, "precision": precision,
            "precision_reason": None if tp + fp else "no_evaluable_alerts", "matched_events": matched,
            "observed_events": len(eligible), "all_observed_events": len(events), "fn_events": len(eligible) - matched,
            "overall_recall": recall, "recall_reason": None if eligible else "no_evaluable_events",
            "available_events": len(available), "events_without_history": len(eligible) - len(available),
            "conditional_recall": sum(e.event_id in used for e in available) / len(available) if available else None,
            "unassessable_alerts": outcomes_count["unassessable"], "edge_alerts": outcomes_count["edge"],
            "fp_reasons": dict(fp_reasons), "excluded_events": dict(excluded), "matches": matches,
            "alert_outcomes": outcomes, "event_outcomes": event_rows,
            "assessable_seconds": context.assessable_seconds,
            "fp_per_30_days": fp / context.assessable_seconds * 30 * 86400 if context.assessable_seconds else None,
            "fp_rate_reason": None if context.assessable_seconds else "no_assessable_time",
            "availability_seconds": dict(availability), "lead_seconds": leads, "daily": daily,
            "unknown_seconds": union_seconds(context.unknown_endpoints),
            "unknown_intervals_count": len(context.unknown_endpoints),
            "origin_counts": origin_counts, "delivery_counts": delivery_counts,
            "past_feature_ready_seconds": ready_seconds, "fresh_seconds": fresh_seconds,
            **trace,
            "precision_ci": block_ci([v[:2] for v in daily.values()]),
            "recall_ci": block_ci([v[2:] for v in daily.values()]),
            "stop_status": stop_status(precision, recall)}
