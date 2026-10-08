"""Хвилинний replay зі справжніми чистими переходами стану AvelRen."""
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from services.backend.src.avelren.surge_events import SurgeState, advance_state
from services.backend.src.avelren.surge_model import SCORE_THRESHOLD, SurgePrediction

from .contracts import Dataset, ObservationRow
from .data import timestamp
from .delivery import DeliveryReplay
from .events import HistoryIndex
from .features import KYIV
from .manifest import Manifest


@dataclass(frozen=True)
class ScoreResult:
    score: float | None
    threshold: float | None
    status: str
    reason: str | None

    def runtime_score(self):
        if self.score is None:
            return None
        if (not math.isfinite(self.score) or not 0 <= self.score <= 1 or self.threshold is None
                or not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1):
            raise ValueError("invalid candidate score or threshold")
        if self.threshold == SCORE_THRESHOLD:
            return self.score
        return 1.0 if self.score >= self.threshold else 0.0


class Candidate(Protocol):
    supported_ids: tuple[int, ...] | None

    def score(self, queue_id: int, rows: Sequence[ObservationRow], origin: datetime) -> ScoreResult: ...


@dataclass
class ReplayResult:
    decisions: list[dict]
    alerts: list[dict]
    availability: list[dict]
    delivery_attempts: list[dict] = field(default_factory=list)
    cancels: list[dict] = field(default_factory=list)


def prepare_tick(index, now, latency_seconds):
    j = bisect_right(index.times, now.timestamp() - latency_seconds) - 1
    lo = bisect_left(index.times, (now - timedelta(hours=4, minutes=3)).timestamp())
    observed = index.rows[j].time if j >= lo else now - timedelta(days=1)
    hour = now.astimezone(KYIV).replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    fresh = j >= lo and now - observed <= timedelta(minutes=3)
    lag = index.lag(j, 5) if fresh else None
    growth = index.rows[j].count - index.rows[lag].count if lag is not None and lag >= lo else None
    quality = fresh and index.past_valid(j)
    if quality and index.lag(j, 240, 300, True) < lo:
        quality = HistoryIndex(index.rows[lo:j + 1]).past_valid(j - lo)
    return j, lo, observed, hour, fresh, growth, quality


class ReplayCache:
    """Лише причинні входи tick; жодного стану моделі/сповіщень між trials."""
    def __init__(self, dataset):
        self.dataset = dataset
        self.indices = {q: HistoryIndex(rows) for q, rows in dataset.rows.items()}
        self.ticks = {}

    def tick(self, queue_id, now, latency):
        key = queue_id, now, latency
        if key not in self.ticks:
            self.ticks[key] = prepare_tick(self.indices[queue_id], now, latency)
        return self.ticks[key]


class ReplayEngine:
    def __init__(self, queue_id: int, candidate: Candidate, enabled_from: datetime):
        self.queue_id, self.candidate, self.enabled_from = queue_id, candidate, enabled_from
        self.state = SurgeState()
        self.last_hour = None
        self.previous = None
        self.active = {}
        self.alerts, self.decisions, self.availability = [], [], []
        self.acknowledged = set()
        self.delivery = DeliveryReplay()
        self.cancels = []

    def acknowledge(self, alert_id: str):
        if any(alert["alert_id"] == alert_id for alert in self.alerts):
            self.acknowledged.add(alert_id)
            self.delivery.acknowledge(alert_id)

    def deliver(self, now: datetime, scenario: str):
        self.delivery.expire(now)
        for key in self.delivery.alerts:
            attempt = self.delivery.reserve(key, now)
            if attempt is not None:
                self.delivery.accept(attempt["attempt_id"], now)
                if scenario == "ack_first":
                    self.acknowledge(key)
        self.cancels.extend({"alert_id": key, "now": now, "queue_id": self.queue_id}
                            for key in self.delivery.drain_cancels())

    def step(self, index: HistoryIndex, now: datetime, latency_seconds: int, prepared=None):
        j, lo, observed, local_hour, fresh, growth, quality = prepared or prepare_tick(index, now, latency_seconds)
        supported = self.candidate.supported_ids is None or self.queue_id in self.candidate.supported_ids
        retry = self.previous is not None and self.previous[1].score is None and self.previous[0] < observed
        prediction, scored = None, None
        if (supported and now >= self.enabled_from and (self.last_hour != local_hour or retry)
                and local_hour <= observed <= now and now - observed <= timedelta(minutes=3)):
            scored = self.candidate.score(self.queue_id, index.rows[lo:j + 1], observed)
            prediction = SurgePrediction(observed, observed + timedelta(hours=1),
                                         observed + timedelta(hours=24), scored.runtime_score(), scored.reason)
            self.previous, self.last_hour = (observed, scored), local_hour
        decision = advance_state(self.state, prediction, growth, observed, now)
        for kind, reason in decision.closed:
            alert = self.active.pop(kind, None)
            if alert is not None:
                alert.update(closed_at=now, close_reason=reason)
        self.state = decision.state
        for kind, episode in (("surge_forecast", self.state.forecast), ("surge_started", self.state.fact)):
            if episode is None:
                continue
            if kind not in self.active:
                alert = {"queue_id": self.queue_id, "kind": kind,
                         "alert_id": f"{self.queue_id}:{kind}:{now.isoformat()}",
                         "alert_created_at": now, "started_at": episode.started_at,
                         "window_start": prediction.window_start if kind == "surge_forecast" else None,
                         "window_end": prediction.window_end if kind == "surge_forecast" else None,
                         "score": scored.score if kind == "surge_forecast" else None,
                         "threshold": scored.threshold if kind == "surge_forecast" else None,
                         "closed_at": None, "close_reason": None}
                self.alerts.append(alert)
                self.active[kind] = alert
            self.active[kind]["expires_at"] = episode.expires_at
            self.delivery.attach(self.active[kind])
        if scored is not None or decision.started or decision.closed:
            self.decisions.append({"queue_id": self.queue_id, "now": now, "observed_at": observed,
                                   "score": scored.score if scored is not None else None,
                                   "prediction_attempt": scored is not None,
                                   "reason": scored.reason if scored is not None else None,
                                   "started": decision.started, "closed": decision.closed,
                                   "forecast_armed": self.state.forecast_armed})
        status = "not_applicable" if not supported else "warmup" if now < self.enabled_from else (
            self.previous[1].status if fresh and self.previous is not None else "unavailable")
        record = {"queue_id": self.queue_id, "status": status, "past_valid": quality, "fresh": fresh}
        if self.availability and all(self.availability[-1][key] == value for key, value in record.items()):
            self.availability[-1]["end"] = now + timedelta(minutes=1)
        else:
            self.availability.append(record | {"start": now, "end": now + timedelta(minutes=1)})
        return decision


def replay(dataset: Dataset, candidate: Candidate, manifest: Manifest, latency_seconds: int,
           delivery_scenario: str = "success_no_ack", *, cache=None, end=None) -> ReplayResult:
    if latency_seconds not in (0, 60):
        raise ValueError("only preregistered latency scenarios supported")
    if delivery_scenario not in ("success_no_ack", "ack_first"):
        raise ValueError("only preregistered delivery scenarios supported")
    settings = manifest.settings
    start = timestamp(settings["replay"]["start"])
    end = end or timestamp(settings["periods"]["development_end"])
    if end not in {timestamp(settings["periods"][p]) for p in ("selection_end", "development_end")}:
        raise ValueError("replay end outside preregistered phases")
    if cache is not None and cache.dataset is not dataset:
        raise ValueError("replay cache belongs to another dataset")
    enabled = timestamp(settings["replay"]["forecast_enabled_from"])
    decisions, alerts, availability = [], [], []
    attempts, cancels = [], []
    for queue_id in manifest.queue_ids:
        if queue_id not in dataset.rows:
            supported = candidate.supported_ids is None or queue_id in candidate.supported_ids
            availability.append({"queue_id": queue_id, "start": start, "end": end,
                                 "status": "data_not_available" if supported else "not_applicable",
                                 "past_valid": False, "fresh": False})
            continue
        engine = ReplayEngine(queue_id, candidate, enabled)
        index = cache.indices[queue_id] if cache is not None else HistoryIndex(dataset.rows[queue_id])
        clock = math.ceil(start.timestamp() / 60) * 60
        while clock < end.timestamp():
            now = datetime.fromtimestamp(clock, UTC)
            engine.step(index, now, latency_seconds, cache.tick(queue_id, now, latency_seconds) if cache else None)
            engine.deliver(now, delivery_scenario)
            clock += 60
        decisions.extend(engine.decisions)
        alerts.extend(engine.alerts)
        availability.extend(engine.availability)
        attempts.extend(engine.delivery.attempts.values())
        cancels.extend(engine.cancels)
    return ReplayResult(sorted(decisions, key=lambda r: (r["now"], r["queue_id"])),
                        sorted(alerts, key=lambda r: (r["alert_created_at"], r["queue_id"], r["alert_id"])),
                        availability, attempts, cancels)
