"""Commit/rollback status is evidence-backed; no production targets."""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from avelren.adoption_inventory import AdoptionError, capture, fingerprint
from avelren.adoption_plan import build_plan, decode_plan, encode_plan


def snapshot(database):
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return capture(conn)


def prepared(database):
    with psycopg.connect(database("admin")) as conn:
        conn.execute("GRANT SELECT ON devices TO PUBLIC")
    return build_plan(snapshot(database))


def test_adoption_waiting_lock_preserves_intervening_grant(database, tmp_path, monkeypatch):
    plan = prepared(database)
    waiting = threading.Event()
    original = psycopg.Connection.execute
    holder = psycopg.connect(database("admin"), autocommit=True)
    holder.execute(
        "SELECT pg_advisory_lock(hashtextextended(current_database() || ':avelren-adoption-016',0))"
    )

    def execute(conn, query, *args, **kwargs):
        if isinstance(query, str) and "SELECT pg_advisory" in query:
            waiting.set()
        return original(conn, query, *args, **kwargs)

    monkeypatch.setattr(psycopg.Connection, "execute", execute)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            future = workers.submit(apply, database, plan, tmp_path / "proof")
            try:
                assert waiting.wait(10), "adoption did not reach serialization lock"
                holder.execute("GRANT DELETE ON devices TO avelren_api")
            finally:
                holder.close()
            with pytest.raises(AdoptionError, match="plan_drift"):
                future.result(timeout=30)
    finally:
        holder.close()
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute(
            "SELECT has_table_privilege('avelren_api','devices','DELETE')"
        ).fetchone()[0]


@pytest.mark.parametrize("damage", ["missing", "tampered"])
def test_adoption_inverse_requires_persisted_commit_proof(database, tmp_path, damage):
    from avelren.postgres_adoption import _inverse

    plan = prepared(database)
    evidence = tmp_path / "proof"
    assert apply(database, plan, evidence).status == "adopted"
    if damage == "missing":
        (evidence / "committed.json").unlink()
    else:
        record = json.loads((evidence / "apply-intent.json").read_text())
        record["plan_sha256"] = "0" * 64
        (evidence / "apply-intent.json").write_text(json.dumps(record))
    with pytest.raises(AdoptionError):
        _inverse(database("admin"), plan.before.database, plan, evidence, failpoint=None)
    assert fingerprint(snapshot(database)) == fingerprint(plan.expected)


@pytest.mark.parametrize("server_committed", [False, True])
def test_adoption_ambiguous_commit_never_retries_or_compensates(
    database,
    tmp_path,
    monkeypatch,
    server_committed,
):
    from avelren import postgres_adoption

    plan = prepared(database)
    commit = psycopg.Connection.commit
    read = postgres_adoption.read_snapshot
    failed = False
    rollback_calls = []

    def lost_ack(conn):
        nonlocal failed
        if "default_transaction_read_only=off" in conn.info.options and not failed:
            if server_committed:
                commit(conn)
            failed = True
            raise psycopg.OperationalError("lost acknowledgement sentinel")
        return commit(conn)

    def unavailable_rollback(conn):
        rollback_calls.append(True)
        raise psycopg.OperationalError("connection unavailable")

    def unavailable_read(dsn):
        if failed:
            raise psycopg.OperationalError("diagnostics unavailable")
        return read(dsn)

    monkeypatch.setattr(psycopg.Connection, "commit", lost_ack)
    monkeypatch.setattr(psycopg.Connection, "rollback", unavailable_rollback)
    monkeypatch.setattr(postgres_adoption, "read_snapshot", unavailable_read)
    result = apply(database, plan, tmp_path / "proof")
    assert result.status == "commit_unknown"
    assert not rollback_calls
    assert (tmp_path / "proof/apply-intent.json").is_file()
    monkeypatch.undo()
    assert fingerprint(snapshot(database)) == fingerprint(
        plan.expected if server_committed else plan.before,
    )


def test_adoption_detects_disabled_constraint_triggers(database):
    before = snapshot(database)
    with psycopg.connect(database("admin")) as conn:
        conn.execute("ALTER TABLE observations DISABLE TRIGGER ALL")
    changed = snapshot(database)
    assert fingerprint(changed) != fingerprint(before)
    with pytest.raises(AdoptionError):
        build_plan(changed)


def test_adoption_refuses_trigger_enablement_drift(database, tmp_path):
    plan = prepared(database)
    with psycopg.connect(database("admin")) as conn:
        conn.execute("ALTER TABLE observations DISABLE TRIGGER ALL")
    changed = fingerprint(snapshot(database))
    with pytest.raises(AdoptionError, match="plan_drift"):
        apply(database, plan, tmp_path / "proof")
    assert fingerprint(snapshot(database)) == changed


def apply(database, plan, path, failpoint=None):
    from avelren.postgres_adoption import apply_disposable

    dsn = database("admin")
    return apply_disposable(dsn, conninfo_to_dict(dsn)["dbname"], plan, path, failpoint=failpoint)


def test_adoption_apply_and_repeat_are_evidence_backed(database, tmp_path):
    plan = prepared(database)
    evidence = tmp_path / "evidence"
    result = apply(database, plan, evidence)
    assert result.status == "adopted"
    assert result.after_fingerprint == fingerprint(plan.expected)
    assert (evidence / "committed.json").is_file()
    assert apply(database, plan, evidence).status == "already_target"
    assert fingerprint(snapshot(database)) == fingerprint(plan.expected)


@pytest.mark.parametrize(
    "failpoint,status,original",
    [
        ("before_commit", "rolled_back", True),
        ("after_commit", "rolled_back", True),
        ("during_inverse", "rollback_failed", False),
        ("receipt_write", "commit_unknown", False),
    ],
)
def test_adoption_failure_states_preserve_transaction_boundaries(
    database,
    tmp_path,
    failpoint,
    status,
    original,
):
    plan = prepared(database)
    result = apply(database, plan, tmp_path / "evidence", failpoint)
    assert result.status == status
    expected = plan.before if original else plan.expected
    assert fingerprint(snapshot(database)) == fingerprint(expected)
    if status == "commit_unknown":
        with pytest.raises(AdoptionError):
            apply(database, plan, tmp_path / "evidence")


def test_adoption_refuses_drift_after_plan(database, tmp_path):
    plan = prepared(database)
    with psycopg.connect(database("admin")) as conn:
        conn.execute("GRANT DELETE ON devices TO avelren_api")
    before = snapshot(database)
    with pytest.raises(AdoptionError, match="plan_drift"):
        apply(database, plan, tmp_path / "evidence")
    assert fingerprint(snapshot(database)) == fingerprint(before)


def test_adoption_refuses_other_application_session(database, tmp_path):
    plan = prepared(database)
    with psycopg.connect(database("api")):
        with pytest.raises(AdoptionError, match="active_sessions"):
            apply(database, plan, tmp_path / "evidence")
    assert fingerprint(snapshot(database)) == fingerprint(plan.before)


def test_adoption_plan_cannot_inject_supplied_sql(database):
    plan = prepared(database)
    data = json.loads(encode_plan(plan))
    data["forward"][0] = "DROP DATABASE avelren"
    with pytest.raises(AdoptionError, match="plan_contract"):
        decode_plan(json.dumps(data).encode())


def test_adoption_refuses_production_target_and_disabled_test_mode(database, tmp_path, monkeypatch):
    from avelren.postgres_adoption import apply_disposable

    plan = prepared(database)
    with pytest.raises(AdoptionError):
        apply_disposable(database("admin"), "avelren", plan, tmp_path / "evidence")
    monkeypatch.delenv("AVELREN_DATABASE_TEST", raising=False)
    with pytest.raises(AdoptionError):
        apply(database, plan, tmp_path / "evidence")
    assert fingerprint(snapshot(database)) == fingerprint(plan.before)


def test_adoption_post_commit_drift_is_not_overwritten(database, tmp_path, monkeypatch):
    from avelren import postgres_adoption

    plan = prepared(database)

    def fail_gate(dsn):
        with psycopg.connect(dsn) as conn:
            conn.execute("GRANT DELETE ON devices TO avelren_api")
        return ["table_acl"]

    monkeypatch.setattr(postgres_adoption, "_run_gate", fail_gate)
    result = apply(database, plan, tmp_path / "evidence")
    assert result.status == "rollback_failed"
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute(
            "SELECT has_table_privilege('avelren_api','devices','DELETE')"
        ).fetchone()[0]


def test_adoption_cli_inventory_plan_apply_inspect(database, tmp_path):
    plan = prepared(database)
    dsn = database("admin")
    env = {
        **os.environ,
        "AVELREN_ADOPTION_DSN": dsn,
        "AVELREN_ADOPTION_TARGET": conninfo_to_dict(dsn)["dbname"],
    }
    evidence = str(tmp_path / "cli-evidence")
    for command, flag, expected in (
        ("inventory", "--output-dir", "inventoried"),
        ("plan", "--evidence-dir", "planned"),
        ("apply-test", "--evidence-dir", "adopted"),
        ("inspect", "--evidence-dir", "inspected"),
    ):
        result = subprocess.run(
            [sys.executable, "-m", "avelren.postgres_adoption", command, flag, evidence],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["status"] == expected
        assert "ci-only" not in result.stdout + result.stderr
    assert fingerprint(snapshot(database)) == fingerprint(plan.expected)


def test_adoption_corrupted_receipt_is_refused(database, tmp_path):
    plan = prepared(database)
    path = tmp_path / "evidence"
    assert apply(database, plan, path).status == "adopted"
    (path / "accepted.json").write_text("null")
    with pytest.raises(AdoptionError, match="receipt_format"):
        apply(database, plan, path)


def test_adoption_inverse_also_refuses_production_target(database, tmp_path):
    from avelren.postgres_adoption import _inverse

    plan = prepared(database)
    with pytest.raises(AdoptionError, match="disposable_target_required"):
        _inverse(database("admin"), "avelren", plan, tmp_path / "evidence", failpoint=None)


@pytest.mark.parametrize(
    "change,restore",
    [
        ("ALTER ROLE avelren_api SUPERUSER", "ALTER ROLE avelren_api NOSUPERUSER"),
        ("GRANT avelren_migrator TO avelren_api", "REVOKE avelren_migrator FROM avelren_api"),
    ],
)
def test_adoption_role_escalation_is_refused(database, change, restore):
    try:
        with psycopg.connect(database("admin")) as conn:
            conn.execute(change)
        with pytest.raises(AdoptionError, match="role_capabilities"):
            build_plan(snapshot(database))
    finally:
        with psycopg.connect(database("admin")) as conn:
            conn.execute(restore)
