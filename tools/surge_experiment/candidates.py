"""Чисте прогнозування кандидатів; жодних числових залежностей у DB parity."""
import math

from .features import KYIV, features_at
from .frozen import FrozenCandidate
from .replay import ScoreResult


class TrainedCandidate:
    def __init__(self, artifact):
        self.artifact = artifact
        self.supported_ids = (17,) if artifact.candidate_id == "chop_local" else None
        self.parameters = artifact.parameters
        self.scales = {int(k): tuple(v) for k, v in self.parameters["scales"].items()}

    def score(self, queue_id, rows, origin):
        if self.supported_ids is not None and queue_id not in self.supported_ids:
            return ScoreResult(None, None, "not_applicable", "unsupported_checkpoint")
        p = self.parameters
        if self.artifact.status != "ready":
            return ScoreResult(None, p["threshold"], "unavailable", self.artifact.status)
        if queue_id not in p["queue_ids"]:
            return ScoreResult(None, p["threshold"], "unavailable", "no_training_history")
        values = features_at(rows, origin, self.scales)
        if values is None:
            return ScoreResult(None, p["threshold"], "unavailable", "insufficient_history")
        kind = self.artifact.candidate_id
        if kind == "calendar":
            local = origin.astimezone(KYIV)
            value = p["cells"].get(f"{queue_id}:{local.weekday()}:{local.hour}", p["prior"])
        else:
            if kind == "trend":
                z = max(-30., min(30., values[1] + values[5]))
            else:
                x = (1., *values)
                if kind == "pooled":
                    x += tuple(float(queue_id == q) for q in p["queue_ids"])
                z = sum(a * b for a, b in zip(x, p["coefficients"], strict=True))
            value = 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))
        return ScoreResult(value, p["threshold"], "available", None)


def load_candidate(artifact):
    return FrozenCandidate() if artifact.candidate_id == "frozen" else TrainedCandidate(artifact)
