"""Скінченний локальний експеримент: fit → selection → зафіксований development."""
import hashlib
import json
from dataclasses import asdict, replace

from .candidates import load_candidate
from .contracts import Dataset
from .data import local_path, timestamp
from .events import build_events, build_large_events, overlap_map
from .features import fit_scales, training_rows
from .metrics import evaluate_alerts, evaluation_context, stop_status
from .replay import ReplayCache, replay
from .report import json_default, report_rows
from .training import FitArtifact, fit_candidate, select_trial


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                      default=json_default, allow_nan=False).encode()


def fit_dataset(dataset, manifest, raw_manifest):
    rows = training_rows(dataset, manifest)
    start, end = (timestamp(manifest.settings["periods"][key]) for key in ("train_start", "train_end"))
    train = Dataset({q: tuple(r for r in history if start <= r.time < end) for q, history in dataset.rows.items()},
                    dataset.source_hashes)
    scales = fit_scales(train, end)
    artifacts = []
    for kind in manifest.settings["candidates"]["ids"]:
        grid = manifest.settings["training"]["lambda_grid"] if kind in ("pooled", "chop_local") else [.01]
        for penalty in grid:
            artifacts.append(asdict(fit_candidate(kind, rows, manifest, regularization=penalty, scales=scales)))
    return {"manifest": raw_manifest, "training_rows": len(rows), "artifacts": artifacts}


def read_fit(path, raw_manifest):
    payload = json.loads(local_path(path).read_text(encoding="utf-8"))
    if payload.get("manifest") != raw_manifest:
        raise ValueError("fit manifest mismatch")
    return payload


class CachedScore:
    def __init__(self, candidate, threshold, values):
        self.candidate, self.threshold, self.values = candidate, threshold, values
        self.supported_ids = candidate.supported_ids

    def score(self, queue_id, rows, origin):
        key = queue_id, origin, rows[0].time if rows else None
        if key not in self.values:
            self.values[key] = self.candidate.score(queue_id, rows, origin)
        value = self.values[key]
        return value if self.threshold is None else replace(value, threshold=self.threshold)


def aggregate(rows):
    tp = sum(r["tp_alerts"] for r in rows)
    fp = sum(r["fp_alerts"] for r in rows)
    matched = sum(r["matched_events"] for r in rows)
    events = sum(r["observed_events"] for r in rows)
    precision, recall = tp / (tp + fp) if tp + fp else None, matched / events if events else None
    return {"tp_alerts": tp, "fp": fp, "matched_events": matched, "observed_events": events,
            "precision": precision, "overall_recall": recall, "stop_status": stop_status(precision, recall)}


def compare(dataset, manifest, fitted, output, *, progress=lambda value: None):
    periods = manifest.settings["periods"]
    train_end, selection_end, development_end = (timestamp(periods[k]) for k in ("train_end", "selection_end", "development_end"))
    cache = ReplayCache(dataset)
    contexts, events, large_slices = {}, {}, {}
    for name, start, end in (("selection", train_end, selection_end), ("development", selection_end, development_end)):
        for q, rows in dataset.rows.items():
            events[name, q] = build_events(rows, end)
            contexts[name, q] = evaluation_context(q, rows, events[name, q], start, end)
            large = build_large_events(rows, end)
            large_slices[f"{name}:{q}"] = {"episodes": [asdict(e) for e in large],
                                           "overlap": overlap_map(events[name, q], large)}

    def metrics(result, phase, candidate):
        return [evaluate_alerts(result, events[phase, q], manifest, context=contexts[phase, q])
                for q in dataset.rows if candidate.supported_ids is None or q in candidate.supported_ids]

    trials, chosen, scenarios, summary, aggregates = [], {}, [], [], []
    lookup = {}
    for index, raw in enumerate(fitted["artifacts"]):
        artifact = FitArtifact(**raw)
        kind = artifact.candidate_id
        penalty = artifact.parameters.get("regularization", 0)
        thresholds = [None] if kind == "frozen" else manifest.settings["training"]["threshold_grid"]
        score_values = {}
        candidate = load_candidate(artifact)
        for threshold in thresholds:
            trial_id = f"{kind}:lambda={penalty}:threshold={threshold}"
            trial = {"trial_id": trial_id, "candidate_id": kind, "artifact_index": index,
                     "period": "selection", "latency_seconds": 0, "delivery_scenario": "success_no_ack",
                     "threshold": threshold or 0, "regularization": penalty, "status": artifact.status}
            if artifact.status == "ready":
                model = CachedScore(candidate, threshold, score_values)
                result = replay(dataset, model, manifest, 0, cache=cache, end=selection_end)
                evaluated = metrics(result, "selection", model)
                trial.update(aggregate(evaluated), queue_results=evaluated)
            else:
                trial.update(precision=None, overall_recall=None, fp=0, queue_results=[])
            trials.append(trial)
            lookup[trial_id] = artifact, threshold
        progress({"stage": "selection", "candidate": kind, "regularization": penalty, "trials": len(trials)})
    # Вибір завершено до першого обчислення метрик development.
    for kind in manifest.settings["candidates"]["ids"]:
        family = [t for t in trials if t["candidate_id"] == kind]
        chosen[kind] = family[0] if kind == "frozen" else select_trial(family)
    (output / "selection.json").write_bytes(encoded({"trials": trials, "chosen": chosen}))
    for kind, selected in chosen.items():
        if selected is None:
            summary.extend({"queue_id": q, "candidate_id": kind, "status": "no_selection_trial",
                            "stop_status": "insufficient_evidence"} for q in dataset.rows)
            continue
        artifact, threshold = lookup[selected["trial_id"]]
        model = CachedScore(load_candidate(artifact), threshold, {})
        for latency in (0, 60):
            for delivery in ("success_no_ack", "ack_first"):
                result = replay(dataset, model, manifest, latency, delivery, cache=cache)
                evaluated = metrics(result, "development", model)
                common = {"candidate_id": kind, "trial_id": selected["trial_id"], "period": "development",
                          "latency_seconds": latency, "delivery_scenario": delivery}
                enriched = [row | common for row in evaluated]
                scenarios.extend(enriched)
                totals = aggregate(evaluated) | common
                aggregates.append(totals)
                if latency == 0 and delivery == "success_no_ack":
                    summary.extend(enriched)
                (output / f"replay-{kind}-{latency}-{delivery}.json").write_bytes(encoded(asdict(result)))
                progress({"stage": "development", **common, "precision": totals["precision"], "recall": totals["overall_recall"]})
    return {"manifest": fitted["manifest"], "fit_sha256": hashlib.sha256(encoded(fitted)).hexdigest(),
            "scope": "partial_pilot" if set(manifest.queue_ids) - set(dataset.rows) else "full_requested_scope",
            "full_38_winner": None, "selected": {key: value["trial_id"] if value else None for key, value in chosen.items()},
            "trials": trials, "scenario_results": scenarios, "aggregate_development": aggregates,
            "large_growth": large_slices, "summary_rows": report_rows(summary, manifest.queue_ids)}
