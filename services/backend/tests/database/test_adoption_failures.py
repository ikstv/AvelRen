"""Commit/rollback status is evidence-backed; no production targets."""

import json

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
