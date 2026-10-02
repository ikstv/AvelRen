"""Експериментальний frozen прогноз напливу зі збережених спостережень.

Бал не є каліброваною ймовірністю. Вхід містить чисту кількість авто,
не окремі реєстрації. Модуль не навчається, не звертається до мережі.
"""

import bisect
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

MODEL_VERSION = "surge_24h_v1"
MODEL_SHA256 = "331320e05c62ec027744dab387ba40c859a9c1070821afc3910f4358bb3b90bb"
SUPPORTED_CHECKPOINTS = (1, 6, 17, 29)
SCORE_THRESHOLD = 0.8789563370805348
KYIV = ZoneInfo("Europe/Kyiv")


@dataclass(frozen=True)
class Observation:
    time: datetime
    vehicles: int
    paused: bool


@dataclass(frozen=True)
class SurgePrediction:
    issued_at: datetime
    window_start: datetime
    window_end: datetime
    score: float | None
    reason: str | None
    model_version: str = MODEL_VERSION


@dataclass(frozen=True)
class FrozenModel:
    mean: tuple[float, ...]
    std: tuple[float, ...]
    coefficients: tuple[float, ...]


def load_model(path: Path) -> FrozenModel:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("surge model checksum mismatch")
    model = json.loads(data)
    mean = tuple(model["feature_mean"])
    std = tuple(model["feature_std"])
    coefficients = tuple(model["coefficients"])
    if len(mean) != 15 or len(std) != 15 or len(coefficients) != 16:
        raise ValueError("invalid surge model dimensions")
    if not all(math.isfinite(v) for v in (*mean, *std, *coefficients)):
        raise ValueError("non-finite surge model")
    if min(std) <= 0 or model["threshold"] != SCORE_THRESHOLD:
        raise ValueError("invalid surge model normalization or threshold")
    return FrozenModel(mean, std, coefficients)


@cache
def frozen_model() -> FrozenModel:
    return load_model(Path(__file__).parent / "models" / "surge_24h_v1.json")


def _aware(t: datetime) -> bool:
    return isinstance(t, datetime) and t.tzinfo is not None and t.utcoffset() is not None


def _past(observations: Sequence[Observation], now: datetime) -> list[Observation] | None:
    if not _aware(now):
        return None
    result = []
    for row in observations:
        if not _aware(row.time):
            return None
        if row.time > now:
            continue
        if (
            not isinstance(row.vehicles, int)
            or isinstance(row.vehicles, bool)
            or row.vehicles < 0
            or not isinstance(row.paused, bool)
        ):
            return None
        result.append(Observation(row.time.astimezone(UTC), row.vehicles, row.paused))
    result.sort(key=lambda row: row.time)
    if any(a.time == b.time for a, b in zip(result, result[1:], strict=False)):
        return None
    return result


def _lag_index(
    rows: list[Observation], minutes: int, max_gap: int, coverage: bool = False
) -> int | None:
    target = rows[-1].time - timedelta(minutes=minutes)
    times = [row.time for row in rows]
    k = bisect.bisect_left(times, target)
    choices = [i for i in (k - 1, k) if 0 <= i < len(rows)]
    if not choices:
        return None
    i = min(choices, key=lambda n: abs((times[n] - target).total_seconds()))
    if abs((times[i] - target).total_seconds()) > 30:
        return None
    if any(
        (b - a).total_seconds() > max_gap for a, b in zip(times[i:], times[i + 1 :], strict=False)
    ):
        return None
    if coverage and (len(rows) - i) / (minutes + 1) < 0.95:
        return None
    return i


def predict_surge(
    checkpoint_id: int, observations: Sequence[Observation], issued_at: datetime
) -> SurgePrediction:
    if _aware(issued_at):
        issued_at = issued_at.astimezone(UTC)

    def result(score: float | None = None, reason: str | None = None) -> SurgePrediction:
        return SurgePrediction(
            issued_at,
            issued_at + timedelta(hours=1),
            issued_at + timedelta(hours=24),
            score,
            reason,
        )

    if checkpoint_id not in SUPPORTED_CHECKPOINTS:
        return result(reason="unsupported_checkpoint")
    rows = _past(observations, issued_at)
    if rows is None:
        return result(reason="invalid_observations")
    if not rows:
        return result(reason="insufficient_history")
    if issued_at - rows[-1].time > timedelta(minutes=3):
        return result(reason="stale_measurement")
    lags = []
    for minutes in (5, 10, 20, 60):
        i = _lag_index(rows, minutes, 90)
        if i is None:
            return result(reason="insufficient_history")
        lags.append(rows[-1].vehicles - rows[i].vehicles)
    if any(_lag_index(rows, minutes, 300, coverage=True) is None for minutes in (120, 240)):
        return result(reason="insufficient_history")
    local = rows[-1].time.astimezone(KYIV)
    phase = local.hour * 60 + local.minute
    features = [
        rows[-1].vehicles,
        *lags,
        lags[0] - lags[1] / 2,
        float(rows[-1].paused),
        math.sin(2 * math.pi * phase / 1440),
        math.cos(2 * math.pi * phase / 1440),
        math.sin(2 * math.pi * local.weekday() / 7),
        math.cos(2 * math.pi * local.weekday() / 7),
        *(int(checkpoint_id == cp) for cp in SUPPORTED_CHECKPOINTS),
    ]
    model = frozen_model()
    z = model.coefficients[0] + sum(
        (v - m) / s * w
        for v, m, s, w in zip(features, model.mean, model.std, model.coefficients[1:], strict=True)
    )
    return result(score=1 / (1 + math.exp(-max(-30.0, min(30.0, z)))))


def detect_growth(observations: Sequence[Observation], issued_at: datetime) -> int | None:
    rows = _past(observations, issued_at)
    if not rows or issued_at - rows[-1].time > timedelta(minutes=3):
        return None
    i = _lag_index(rows, 5, 90)
    return None if i is None else rows[-1].vehicles - rows[i].vehicles
