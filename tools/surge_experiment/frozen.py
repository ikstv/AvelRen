"""Незмінний frozen inference лише для чотирьох підтримуваних черг."""
from services.backend.src.avelren.surge_model import (
    SCORE_THRESHOLD,
    SUPPORTED_CHECKPOINTS,
    Observation,
    predict_surge,
)

from .replay import ScoreResult


class FrozenCandidate:
    supported_ids = SUPPORTED_CHECKPOINTS

    def score(self, queue_id, rows, origin):
        if queue_id not in self.supported_ids:
            return ScoreResult(None, None, "not_applicable", "unsupported_checkpoint")
        result = predict_surge(queue_id, [Observation(r.time, r.count, r.paused) for r in rows], origin)
        return ScoreResult(result.score, SCORE_THRESHOLD, "available" if result.score is not None else "unavailable", result.reason)
