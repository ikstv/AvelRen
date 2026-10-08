"""Обмежений fit v1; validation/development не беруть участі у навчанні."""
import hashlib
import json
import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from threadpoolctl import threadpool_limits

from .data import timestamp
from .features import KYIV, assign_weights


@dataclass(frozen=True)
class FitArtifact:
    candidate_id: str
    parameters: dict
    train_hashes: dict
    status: str


def objective(beta, x, y, weights, regularization, offset_count):
    z = x @ beta
    penalty = np.full(len(beta), regularization)
    penalty[0] = 0
    if offset_count:
        penalty[-offset_count:] *= 10
    loss = np.dot(weights, np.logaddexp(0, z) - y * z) + np.dot(penalty, beta * beta) / 2
    gradient = x.T @ (weights * (expit(z) - y)) + penalty * beta
    return float(loss), gradient


def fit_candidate(candidate_id, rows, manifest, *, regularization=0.01, scales=None):
    config = manifest.settings
    if candidate_id not in config["candidates"]["ids"]:
        raise ValueError("unknown candidate")
    if regularization not in config["training"]["lambda_grid"]:
        raise ValueError("regularization outside preregistered grid")
    start, end = (timestamp(config["periods"][key]) for key in ("train_start", "train_end"))
    known = sorted((r for r in rows if start <= r.origin < end and r.label.value in (0, 1)
                    and r.label.dependency_end < end and r.queue_id in manifest.queue_ids
                    and (candidate_id != "chop_local" or r.queue_id == 17)),
                   key=lambda r: (r.origin, r.queue_id))
    if any(len(r.values) != 11 or not all(math.isfinite(v) for v in r.values) for r in known):
        raise ValueError("invalid training features")
    if len({(r.queue_id, r.origin) for r in known}) != len(known):
        raise ValueError("duplicate training origin")
    known = assign_weights(known)
    encoded = [(r.queue_id, r.origin.isoformat(), r.values, r.label.value, r.label.event_ids,
                r.label.dependency_end.isoformat(), r.weight) for r in known]
    hashes = {"feature_rows": hashlib.sha256(json.dumps(encoded, separators=(",", ":")).encode()).hexdigest(),
              **{p.name: sha for p, sha in manifest.inputs}}
    queues = sorted({r.queue_id for r in known})
    params = {"queue_ids": queues, "scales": {str(k): list(v) for k, v in (scales or {}).items()},
              "regularization": regularization if candidate_id in ("pooled", "chop_local") else 0,
              "threshold": 0.5, "training_origins": len(known)}
    if candidate_id == "frozen":
        return FitArtifact(candidate_id, {}, hashes, "ready")
    if candidate_id == "trend":
        return FitArtifact(candidate_id, params, hashes, "ready" if known else "insufficient_history")
    if len({r.label.value for r in known}) < 2:
        return FitArtifact(candidate_id, params, hashes, "insufficient_training_classes")
    w = np.asarray([r.weight for r in known], dtype=float)
    w /= w.sum()
    y = np.asarray([r.label.value for r in known], dtype=float)
    if candidate_id == "calendar":
        w *= len(known)
        prior = float((w @ y + 1) / (w.sum() + 2))
        cells = {}
        for row, weight in zip(known, w, strict=True):
            local = row.origin.astimezone(KYIV)
            key = f"{row.queue_id}:{local.weekday()}:{local.hour}"
            values = cells.setdefault(key, [0., 0.])
            values[0] += float(weight) * row.label.value
            values[1] += float(weight)
        params.update(prior=prior, cells={key: (total + 10 * prior) / (weight + 10)
                                         for key, (total, weight) in sorted(cells.items())})
        return FitArtifact(candidate_id, params, hashes, "ready")
    offset_count = len(queues) if candidate_id == "pooled" else 0
    x = np.asarray([[1., *r.values, *([float(r.queue_id == q) for q in queues] if offset_count else [])]
                    for r in known], dtype=float)
    with threadpool_limits(limits=1, user_api="blas"):
        fitted = minimize(objective, np.zeros(x.shape[1]), args=(x, y, w, regularization, offset_count),
                          jac=True, method="L-BFGS-B", options={"maxiter": 1000, "gtol": 1e-8})
    params.update(optimizer_status=int(fitted.status), iterations=int(fitted.nit))
    if not fitted.success or not np.isfinite(fitted.x).all():
        return FitArtifact(candidate_id, params, hashes, "optimizer_not_converged")
    params["coefficients"] = fitted.x.tolist()
    return FitArtifact(candidate_id, params, hashes, "ready")


def select_trial(trials):
    if any(t["period"] != "selection" or t["latency_seconds"] != 0
           or t["delivery_scenario"] != "success_no_ack" for t in trials):
        raise ValueError("selection requires primary selection replay only")
    known = [t for t in trials if t["precision"] is not None and t["overall_recall"] is not None]
    if not known:
        return None

    def rank(t):
        p, r = t["precision"], t["overall_recall"]
        harmonic = 2 * p * r / (p + r) if p + r else 0.
        return (-min(p, r), -harmonic, t["fp"], -t["threshold"], -t["regularization"], t["trial_id"])
    return min(known, key=rank)
