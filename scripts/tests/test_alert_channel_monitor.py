"""#113: the external alert-channel gate's threshold logic, seen red.

This is the "gate red" proof the owner required (correction 3): we assert that
an empty channel makes the gate fire, and that a stably-blind probe fires too,
while a transient unknown does not. No DB, no network — pure decision logic.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

# The classifier lives under scripts/ (shipped with the workflow), not in the
# app package — load it by path.
_MOD = Path(__file__).resolve().parents[1] / "classify_alert_channel.py"
_spec = importlib.util.spec_from_file_location("classify_alert_channel", _MOD)
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_empty_fires_immediately() -> None:
    # A single empty probe is enough — the alarm path is really down.
    assert gate.classify(["empty"]) == "empty"
    assert gate.is_outage("empty") is True


def test_empty_wins_over_other_verdicts() -> None:
    assert gate.classify(["ok", "empty", "unknown"]) == "empty"


def test_stably_blind_fires() -> None:
    assert gate.classify(["unknown"] * gate.BLIND_STREAK) == "blind"
    assert gate.is_outage("blind") is True


def test_transient_unknown_does_not_fire() -> None:
    # unknown mixed with a good read is not an outage — no crying wolf.
    assert gate.classify(["unknown", "ok", "unknown"]) == "ok"
    assert gate.is_outage("ok") is False


def test_too_few_unknown_does_not_fire() -> None:
    assert gate.classify(["unknown"]) == "ok"


def test_no_reading_is_not_a_clean_bill() -> None:
    assert gate.classify([]) == "blind"


def test_ok_is_healthy() -> None:
    assert gate.classify(["ok", "ok", "ok"]) == "ok"
    assert gate.is_outage("ok") is False


def test_cli_reports_empty_and_nonzero_exit() -> None:
    result = subprocess.run(
        [sys.executable, str(_MOD), "ok", "empty", "unknown"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == "empty\n"
    assert result.stderr == ""


def test_cli_reports_transient_unknown_without_alarm() -> None:
    result = subprocess.run(
        [sys.executable, str(_MOD), "unknown", "ok", "unknown"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "ok\n"
    assert result.stderr == ""
