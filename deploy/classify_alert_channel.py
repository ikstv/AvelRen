#!/usr/bin/env python3
"""Threshold logic for the external alert-channel gate (#113).

Kept separate from the workflow's curl/GitHub plumbing so the DECISION can be
seen red in a unit test — a gate nobody watched go red is not a gate.

The external monitor probes the public /health `alert_channel` a few times in a
row and passes the verdicts here:

  * "empty"  → the watchdog channel has no admin with a live token. This is a
    real, actionable outage of the alarm path — raise IMMEDIATELY (a single
    empty probe is enough).
  * "unknown" → the probe itself could not be computed (degraded /health). A
    transient unknown must NOT cry wolf, but a channel that is *stably* blind is
    a dead gate that has no right to look calm — so raise only after N in a row.
  * "ok" → at least one admin with a live token. Healthy.

Precedence: any "empty" wins (most actionable). Otherwise all-"unknown" over the
window is "blind". Otherwise "ok".
"""

from __future__ import annotations

import sys

# How many consecutive "unknown" verdicts count as a stably-blind gate.
BLIND_STREAK = 3


def classify(probes: list[str]) -> str:
    """Reduce a window of per-probe verdicts to a gate decision.

    Returns one of: "empty" (raise now), "blind" (raise: stably unreadable),
    "ok" (healthy). An empty input is treated as "blind" — no reading is not a
    clean bill of health.
    """
    if not probes:
        return "blind"
    if any(p == "empty" for p in probes):
        return "empty"
    if len(probes) >= BLIND_STREAK and all(p == "unknown" for p in probes):
        return "blind"
    return "ok"


def is_outage(decision: str) -> bool:
    return decision in ("empty", "blind")


if __name__ == "__main__":
    # Usage: classify_alert_channel.py <probe> [<probe> ...]
    # Prints the decision and exits non-zero on an outage (for shell gating).
    decision = classify(sys.argv[1:])
    print(decision)
    raise SystemExit(1 if is_outage(decision) else 0)
