"""Durable visibility of the secondary pipeline and honest recovery (OBS-1/OBS-2).

We protect two invariants:
  * an alerts/ETA failure becomes visible to the watchdog (not just a log line);
  * resolved_at is set immediately when the problem is gone, but recovery is
    considered delivered only on the fact — otherwise a lost push would silently
    hide the recovery.
"""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import db, watchdog

DSN = os.environ["DATABASE_URL"]


def _run(coro_factory):
    async def wrap():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await coro_factory(ac)

    return asyncio.run(wrap())


def _add_run(conn, at: datetime, *, error=None, derived_error=None) -> None:
    conn.execute(
        "INSERT INTO collector_runs (time, error, derived_error) VALUES (%s, %s, %s)",
        (at, error, derived_error),
    )


# --- OBS-1: derived status --------------------------------------------------


def test_record_derived_success_and_failure(conn):
    at = datetime.now(UTC).replace(microsecond=0)
    _add_run(conn, at)

    _run(lambda ac: db.record_derived(ac, at, error=None))
    r = conn.execute(
        "SELECT derived_processed_at, derived_error FROM collector_runs WHERE time=%s", (at,)
    ).fetchone()
    assert r["derived_processed_at"] is not None
    assert r["derived_error"] is None

    _run(lambda ac: db.record_derived(ac, at, error="ETA failed"))
    r = conn.execute(
        "SELECT derived_error FROM collector_runs WHERE time=%s", (at,)
    ).fetchone()
    assert r["derived_error"] == "ETA failed"

    conn.execute("DELETE FROM collector_runs WHERE time=%s", (at,))


def test_watchdog_sees_derived_errors(conn):
    """10+ derived errors in a half hour → the watchdog raises a problem, even if
    fetch and observations are fine (exactly the scenario that was previously
    invisible)."""
    base = datetime.now(UTC).replace(microsecond=0)
    times = [base - timedelta(minutes=i) for i in range(12)]
    for t in times:
        _add_run(conn, t, derived_error="boom")

    problems = _run(watchdog._checks)
    assert "derived_errors" in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


def test_watchdog_ignores_few_derived_errors(conn):
    base = datetime.now(UTC).replace(microsecond=0)
    times = [base - timedelta(minutes=i) for i in range(3)]
    for t in times:
        _add_run(conn, t, derived_error="boom")

    problems = _run(watchdog._checks)
    assert "derived_errors" not in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


def test_watchdog_sees_stuck_derived_after_grace(conn):
    """B3 hard-crash: rows with derived_processed_at=NULL and derived_error=NULL,
    older than grace, are a signal that secondary crashed without an exception
    (SIGKILL/OOM). Previously the watchdog did not catch this."""
    base = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=5)
    times = [base - timedelta(minutes=i) for i in range(watchdog.DERIVED_STUCK_THRESHOLD + 1)]
    for t in times:
        # Explicitly NULL/NULL — we simulate a cycle that did not write the derived status.
        conn.execute("INSERT INTO collector_runs (time) VALUES (%s)", (t,))

    problems = _run(watchdog._checks)
    assert "derived_stuck" in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


def test_watchdog_ignores_stuck_within_grace(conn):
    """A fresh cycle (younger than grace) might not have written the status yet — not an alarm."""
    now = datetime.now(UTC).replace(microsecond=0)
    times = [now - timedelta(seconds=10 * i) for i in range(watchdog.DERIVED_STUCK_THRESHOLD + 2)]
    for t in times:
        conn.execute("INSERT INTO collector_runs (time) VALUES (%s)", (t,))

    problems = _run(watchdog._checks)
    assert "derived_stuck" not in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


# --- OBS-2: separation of resolved / recovery ------------------------------


def _health_alert(conn, kind: str, *, resolved_ago_days=None) -> int:
    resolved = (
        None if resolved_ago_days is None
        else datetime.now(UTC) - timedelta(days=resolved_ago_days)
    )
    return conn.execute(
        "INSERT INTO health_alerts (kind, detail, resolved_at) VALUES (%s, 'x', %s) RETURNING id",
        (kind, resolved),
    ).fetchone()["id"]


def test_recovery_delivered_sets_notified(conn, device, monkeypatch):
    """Successful delivery → recovery_notified_at is set."""
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token='tok-admin' WHERE id=%s",
        (device.device_id,),
    )
    hid = _health_alert(conn, "collector_silent", resolved_ago_days=0)

    async def ok_send(*a, **k):
        return None

    monkeypatch.setattr("avelren.fcm.send", ok_send)
    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert conn.execute(
        "SELECT recovery_notified_at IS NOT NULL AS ok FROM health_alerts WHERE id=%s", (hid,)
    ).fetchone()["ok"] is True
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


def test_recovery_stays_pending_when_delivery_fails(conn):
    """No admin device → _notify returns False → recovery stays unnotified
    (young), we keep retrying. Without OBS-2, resolved_at would lie that
    everything is closed."""
    hid = _health_alert(conn, "db_size", resolved_ago_days=0)

    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert conn.execute(
        "SELECT recovery_notified_at FROM health_alerts WHERE id=%s", (hid,)
    ).fetchone()["recovery_notified_at"] is None
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


def test_recovery_given_up_sets_abandoned_not_notified(conn):
    """B2: give-up writes recovery_abandoned_at, NOT recovery_notified_at —
    the DB must distinguish "delivered" from "gave up"."""
    hid = _health_alert(conn, "reboot_required", resolved_ago_days=2)

    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    r = conn.execute(
        "SELECT recovery_notified_at, recovery_abandoned_at FROM health_alerts WHERE id=%s",
        (hid,),
    ).fetchone()
    assert r["recovery_abandoned_at"] is not None
    assert r["recovery_notified_at"] is None
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


def test_recovery_not_resent_when_already_notified(conn, device, monkeypatch):
    """B1: a row with recovery_notified_at already set (e.g. a migration backfill
    for legacy resolved) is not resent."""
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token='tok-admin' WHERE id=%s",
        (device.device_id,),
    )
    hid = conn.execute(
        "INSERT INTO health_alerts (kind, detail, resolved_at, recovery_notified_at) "
        "VALUES ('collector_silent', 'x', now() - INTERVAL '10 days', "
        "now() - INTERVAL '10 days') RETURNING id"
    ).fetchone()["id"]

    calls = []

    async def spy_send(*a, **k):
        calls.append(1)

    monkeypatch.setattr("avelren.fcm.send", spy_send)
    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert calls == []  # no send for a historical resolved alert
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


# --- M-12: alert on a stale backup ------------------------------------------


def _write_snapshot(monkeypatch, tmp_path, data):
    snap = tmp_path / "host.json"
    snap.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", snap)


def test_backup_age_hours(monkeypatch, tmp_path):
    """A pure helper: None without snapshot/field, age from snapshot, stale threshold."""
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", tmp_path / "absent.json")

    # No snapshot — a fresh deploy or a just-rebooted host: there must be NO alarm.
    assert watchdog._backup_age_hours() is None

    # The field is there but null (the stamp was not created yet) — also None, not a false alarm.
    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": None}})
    assert watchdog._backup_age_hours() is None

    # A fresh backup — almost zero hours, not a problem.
    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": 0.5}})
    assert watchdog._backup_age_hours() < 1

    # 40 h without a backup — that is ≥2 daily runs in a row, a real problem.
    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": 40.0}})
    assert watchdog._backup_age_hours() > watchdog.BACKUP_STALE_HOURS

    # 30 h — one missed daily run is still tolerable, we do not wake the admin.
    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": 30.0}})
    assert watchdog._backup_age_hours() < watchdog.BACKUP_STALE_HOURS


def test_backup_stale_surfaces_in_checks(conn, monkeypatch, tmp_path):
    """A stale age raises the 'backup_stale' problem; a fresh one removes it."""
    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": 40.0}})
    assert "backup_stale" in _run(watchdog._checks)

    _write_snapshot(monkeypatch, tmp_path, {"backups": {"age_hours": 0.0}})
    assert "backup_stale" not in _run(watchdog._checks)


# --- #160: the migration pin is a guard nobody was watching --------------------


def test_migrate_pin_lost_only_on_an_explicit_false(monkeypatch, tmp_path):
    """The three states are not two.

    The pin fell out of the host override during the #88 window and nothing
    noticed for weeks, so the watchdog now watches it. But a watchdog that treats
    "could not look" as "broken" gets muted within a week, and then the real
    signal arrives to an audience that has learned to ignore it.
    """
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", tmp_path / "absent.json")
    assert watchdog._migrate_pin_lost() is False, "no snapshot is not evidence of a lost pin"

    # null — the snapshot ran but could not inspect the compose model (no docker,
    # no stack dir). Unknown, not broken.
    _write_snapshot(monkeypatch, tmp_path, {"docker": {"migrate_pin_active": None}})
    assert watchdog._migrate_pin_lost() is False

    # An older snapshot written before this field existed.
    _write_snapshot(monkeypatch, tmp_path, {"docker": {}})
    assert watchdog._migrate_pin_lost() is False

    _write_snapshot(monkeypatch, tmp_path, {"docker": {"migrate_pin_active": True}})
    assert watchdog._migrate_pin_lost() is False

    # The measured bad state: /migrations resolves somewhere other than the pin.
    _write_snapshot(monkeypatch, tmp_path, {"docker": {"migrate_pin_active": False}})
    assert watchdog._migrate_pin_lost() is True


def test_migrate_pin_lost_surfaces_in_checks(conn, monkeypatch, tmp_path):
    """The problem reaches the alert channel, and clears when the pin returns."""
    _write_snapshot(monkeypatch, tmp_path, {"docker": {"migrate_pin_active": False}})
    problems = _run(watchdog._checks)
    assert "migrate_pin_lost" in problems
    assert "010" in problems["migrate_pin_lost"], "the message must name what gets stamped"

    _write_snapshot(monkeypatch, tmp_path, {"docker": {"migrate_pin_active": True}})
    assert "migrate_pin_lost" not in _run(watchdog._checks)


# --- #164: the installed snapshot script is not the deployed one --------------


def test_snapshot_script_drift_is_silent_only_on_an_exact_match(monkeypatch, tmp_path):
    """The installed copy drifted 125 lines behind the repo and nothing said so.

    Note the deliberate asymmetry with the migrate pin above: there, a missing
    value means "the probe could not look" and must stay quiet. Here a missing
    value means the installed script predates the field itself — which is the
    drift. Same shape, opposite reading, and the difference is whether the absence
    has an innocent explanation.
    """
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", tmp_path / "absent.json")
    assert watchdog._snapshot_script_drift() is None, "no snapshot at all is not drift"

    _write_snapshot(monkeypatch, tmp_path, {"script_sha256": watchdog.EXPECTED_SNAPSHOT_SHA})
    assert watchdog._snapshot_script_drift() is None

    # Today's production state: a script old enough not to know the field.
    _write_snapshot(monkeypatch, tmp_path, {"system": {}})
    reason = watchdog._snapshot_script_drift()
    assert reason is not None and "older than the field" in reason

    # A different script — installed by hand, or an install that did not happen.
    _write_snapshot(monkeypatch, tmp_path, {"script_sha256": "0" * 64})
    reason = watchdog._snapshot_script_drift()
    assert reason is not None
    assert "000000000000" in reason and watchdog.EXPECTED_SNAPSHOT_SHA[:12] in reason


def test_snapshot_script_drift_surfaces_in_checks(conn, monkeypatch, tmp_path):
    _write_snapshot(monkeypatch, tmp_path, {"script_sha256": "0" * 64})
    assert "snapshot_script_drift" in _run(watchdog._checks)

    _write_snapshot(monkeypatch, tmp_path, {"script_sha256": watchdog.EXPECTED_SNAPSHOT_SHA})
    assert "snapshot_script_drift" not in _run(watchdog._checks)
