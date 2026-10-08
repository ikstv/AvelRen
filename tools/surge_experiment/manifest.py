"""Протокол v1 фіксується до fit; невідомі/пропущені параметри відхиляються."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .data import local_path


def protocol_v1() -> dict:
    return {
        "periods": {"train_start": "2026-08-06T00:00:00+03:00",
                    "train_end": "2026-09-18T00:00:00+03:00",
                    "selection_end": "2026-09-25T00:00:00+03:00",
                    "development_end": "2026-10-02T00:00:00+03:00"},
        "replay": {"start": "2026-09-16T22:00:00+03:00", "warmup_hours": 26,
                   "forecast_enabled_from": "2026-09-18T00:00:00+03:00",
                   "initial_state": {"forecast": None, "fact": None, "forecast_armed": True,
                                     "last_observation_at": None, "last_forecast_hour": None,
                                     "attempts": [], "ack": []},
                   "latencies_seconds": [0, 60], "tick_seconds": 60,
                   "subscriber_from": "replay_start", "delivery": ["success_no_ack", "ack_first"],
                   "carry_state": True, "forecast_horizon_hours": [1, 24],
                   "freshness_seconds": 180, "forecast_expiry_minutes": 65,
                   "fact_expiry_minutes": 30, "reminder_seconds": 300, "retry_seconds": 60},
        "labels": {"growth": 20, "lag_seconds": 300, "tolerance_seconds": 30,
                   "max_gap_seconds": 90, "merge_seconds": 1800,
                   "large_growth": 200, "large_window_seconds": 1200,
                   "unknown": None, "purge": "actual_dependency_end"},
        "features": ["count_scaled", "d5_scaled", "d10_scaled", "d20_scaled", "d60_scaled",
                     "acceleration_scaled", "paused", "sin_day", "cos_day", "sin_week", "cos_week"],
        "training": {"seed": 20261009, "lambda_grid": [0.001, 0.01, 0.1],
                     "threshold_grid": [x / 100 for x in range(5, 100, 5)] + [0.99],
                     "optimizer": "L-BFGS-B", "maxiter": 1000, "gtol": 1e-8,
                     "initial_coefficients": 0, "blas_threads": 1, "queue_penalty_multiplier": 10,
                     "weights": "event_or_negative_day_then_equal_queue",
                     "scale": "train_median_and_max_1_iqr", "long_quality": [120, 240, 300, 0.95]},
        "candidates": {"ids": ["calendar", "trend", "frozen", "pooled", "chop_local"],
                       "frozen_ids": [1, 6, 17, 29], "local_ids": [17],
                       "calendar_pseudocount": 10, "calendar_global_prior": [1, 2],
                       "trend": "sigmoid_clip_d5_plus_acceleration_over_scale_30"},
        "metrics": {"matching": "created_queue_id_then_onset_event_id_one_to_one",
                    "duplicate_unmatched": "fp_only_if_future_known", "lead": "onset_minus_created",
                    "development_alert_cohort": ["S", "E-24h-35m"],
                    "development_event_cohort": ["S+24h", "E-23h-35m"],
                    "label_cutoff": "E", "target": [0.99, 0.99],
                    "ranking": ["min_precision_recall", "harmonic_mean", "fewer_fp", "higher_threshold",
                                "higher_lambda", "stable_id"],
                    "confidence": {"method": "moving_block_percentile", "block_days": 7,
                                   "resamples": 2000, "seed": 20261009, "level": 0.95,
                                   "minimum_days": 28, "minimum_valid_fraction": 0.9,
                                   "degenerate": "null", "exact_diagnostic": "independence_assumed"},
                    "stop_rule": "criterion_not_met_or_insufficient_evidence_no_extra_fit"},
    }


@dataclass(frozen=True)
class Manifest:
    queue_ids: tuple[int, ...]
    inputs: tuple[tuple[Path, str], ...]
    code_commit: str
    protocol_json: str

    @property
    def settings(self) -> dict:
        return json.loads(self.protocol_json)


def validate_manifest(config: dict) -> Manifest:
    required = {"version", "queue_ids", "inputs", "code_commit", "protocol"}
    if not isinstance(config, dict) or set(config) != required or config["version"] != "shared-surge-v1":
        raise ValueError("invalid or incomplete manifest")
    if json.dumps(config["protocol"], sort_keys=True) != json.dumps(protocol_v1(), sort_keys=True):
        raise ValueError("manifest protocol missing or changed; new version required")
    ids = config["queue_ids"]
    if not isinstance(ids, list) or not ids or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("invalid manifest queue IDs")
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate manifest queue IDs")
    if not isinstance(config["code_commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", config["code_commit"]):
        raise ValueError("manifest requires code commit")
    if not isinstance(config["inputs"], list) or not config["inputs"]:
        raise ValueError("manifest requires local inputs")
    inputs = []
    for item in config["inputs"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("invalid manifest input")
        if not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("manifest requires source SHA256")
        if not isinstance(item["path"], str):
            raise ValueError("manifest requires local input path")  # noqa: TRY004 - external schema
        inputs.append((local_path(item["path"]), item["sha256"]))
    if len({p.name for p, _ in inputs}) != len(inputs):
        raise ValueError("duplicate manifest input name")
    return Manifest(tuple(sorted(ids)), tuple(inputs), config["code_commit"],
                    json.dumps(config["protocol"], sort_keys=True, allow_nan=False))
