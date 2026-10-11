"""Transaction boundaries remain conservative when PostgreSQL acknowledgements fail."""

from dataclasses import replace
from importlib import import_module

import psycopg
import pytest

from avelren.adoption_inventory import SECTIONS, AdoptionError, Snapshot, fingerprint
from avelren.adoption_plan import AdoptionPlan


class Database:
    """External connection double with durable state independent of pending writes."""

    def __init__(self, direction="forward"):
        before = Snapshot(1, "unit_database", {name: [] for name in SECTIONS})
        after = replace(before, database="unit_target")
        self.plan = AdoptionPlan(1, before, after, ("forward SQL",), ("inverse SQL",))
        self.source = before if direction == "forward" else after
        self.target = after if direction == "forward" else before
        self.durable = self.source
        self.pending = self.source
        self.events = []
        self.commit_error = False
        self.server_committed = False
        self.rollback_error = False
        self.close_error = False
        self.read_error = False
        self.statement_error = False

    def execute(self, statement):
        self.events.append(statement)
        self.pending = self.target
        if self.statement_error:
            raise psycopg.OperationalError("private SQL detail")

    def commit(self):
        self.events.append("commit")
        if self.server_committed or not self.commit_error:
            self.durable = self.pending
        if self.commit_error:
            raise psycopg.OperationalError("private DSN detail")

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error:
            raise psycopg.OperationalError("private rollback detail")
        self.pending = self.durable

    def close(self):
        self.events.append("close")
        if self.close_error:
            raise psycopg.OperationalError("private close detail")

    def read(self, dsn):
        self.events.append("read")
        if self.read_error:
            raise psycopg.OperationalError("private read detail")
        return self.durable


def engine(monkeypatch, database):
    module = import_module("avelren.adoption_transaction")
    monkeypatch.setattr(module, "decode_plan", lambda payload: database.plan)
    monkeypatch.setattr(module.psycopg, "connect", lambda *args, **kwargs: database)
    monkeypatch.setattr(
        module, "acquire_adoption_locks", lambda conn, name: conn.events.append("locks")
    )
    monkeypatch.setattr(module, "_capture_catalog", lambda conn: conn.pending)
    monkeypatch.setattr(module, "read_snapshot", database.read)
    return module


@pytest.mark.parametrize("server_committed", [False, True])
def test_adoption_mutation_commit_ack_loss_closes_connection(monkeypatch, server_committed):
    db = Database()
    db.commit_error = True
    db.server_committed = server_committed
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "private DSN",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=lambda conn: None,
    )
    assert (result.status, result.category, result.fingerprint) == (
        "commit_unknown",
        "commit_acknowledgement_unavailable",
        None,
    )
    assert db.events == ["locks", "forward SQL", "commit", "close"]
    assert db.durable == (db.target if server_committed else db.source)


def test_adoption_inverse_commit_ack_loss_is_unknown(monkeypatch):
    db = Database("inverse")
    db.commit_error = True
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="inverse",
        before_write=lambda conn: None,
        before_commit=lambda conn: None,
    )
    assert result.status == "commit_unknown"
    assert result.fingerprint is None
    assert db.events == ["locks", "inverse SQL", "commit", "close"]


@pytest.mark.parametrize("direction", ["forward", "inverse"])
def test_adoption_mutation_commits_only_after_both_callbacks(monkeypatch, direction):
    db = Database(direction)
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction=direction,
        before_write=lambda conn: conn.events.append("before_write"),
        before_commit=lambda conn: conn.events.append("before_commit"),
    )
    assert (result.status, result.category, result.fingerprint) == (
        "committed",
        None,
        fingerprint(db.target),
    )
    assert db.events == [
        "locks",
        "before_write",
        direction + " SQL",
        "before_commit",
        "commit",
        "close",
    ]


@pytest.mark.parametrize("raised", [False, True])
def test_adoption_callback_refusal_closes_without_mutation(monkeypatch, raised):
    db = Database()
    module = engine(monkeypatch, db)

    def refuse(conn):
        error = AdoptionError("callback_refusal")
        if raised:
            raise error
        return error

    with pytest.raises(AdoptionError, match="callback_refusal"):
        module.run_mutation(
            "dsn",
            db.plan,
            direction="forward",
            before_write=refuse,
            before_commit=lambda conn: None,
        )
    assert db.events == ["locks", "rollback", "close"]


@pytest.mark.parametrize("failure", ["rollback_error", "close_error"])
def test_adoption_refusal_cleanup_failure_is_not_hidden(monkeypatch, failure):
    db = Database()
    setattr(db, failure, True)
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: AdoptionError("refused"),
        before_commit=lambda conn: None,
    )
    assert result.status == "rollback_failed"
    assert result.fingerprint is None
    assert db.events == ["locks", "rollback", "close"]


def test_adoption_foreign_drift_is_preserved_without_mutation(monkeypatch):
    db = Database()
    db.durable = db.pending = replace(db.source, database="foreign_drift")
    module = engine(monkeypatch, db)
    with pytest.raises(AdoptionError, match="plan_drift"):
        module.run_mutation(
            "dsn",
            db.plan,
            direction="forward",
            before_write=lambda conn: None,
            before_commit=lambda conn: None,
        )
    assert db.events == ["locks", "rollback", "close"]
    assert db.durable.database == "foreign_drift"


def test_adoption_recaptures_source_after_before_write_callback(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)

    def drift(conn):
        conn.durable = conn.pending = replace(conn.source, database="foreign_drift")

    with pytest.raises(AdoptionError, match="plan_drift"):
        module.run_mutation(
            "dsn",
            db.plan,
            direction="forward",
            before_write=drift,
            before_commit=lambda conn: None,
        )
    assert db.events == ["locks", "rollback", "close"]
    assert db.durable.database == "foreign_drift"


@pytest.mark.parametrize("direction", ["forward", "inverse"])
def test_adoption_verifies_destination_before_commit_callback(monkeypatch, direction):
    db = Database(direction)
    module = engine(monkeypatch, db)
    monkeypatch.setattr(db, "execute", lambda sql: db.events.append(sql))
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction=direction,
        before_write=lambda conn: None,
        before_commit=lambda conn: conn.events.append("before_commit"),
    )
    assert (result.status, result.category, result.fingerprint) == (
        "rolled_back",
        direction + "_verification",
        fingerprint(db.source),
    )
    assert db.events == ["locks", direction + " SQL", "rollback", "close", "read"]


def test_adoption_rollback_catalog_drift_cannot_claim_restoration(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)
    foreign = replace(db.source, database="foreign_drift")
    monkeypatch.setattr(module, "read_snapshot", lambda dsn: foreign)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=lambda conn: AdoptionError("refused"),
    )
    assert (result.status, result.category, result.fingerprint) == (
        "rollback_failed",
        "pre_commit_unverified",
        fingerprint(foreign),
    )
    assert db.events == ["locks", "forward SQL", "rollback", "close"]


@pytest.mark.parametrize("failure", [None, "rollback_error", "read_error"])
def test_adoption_statement_failure_requires_separate_rollback_proof(monkeypatch, failure):
    db = Database()
    db.statement_error = True
    if failure:
        setattr(db, failure, True)
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=lambda conn: None,
    )
    assert result.status == ("rolled_back" if failure is None else "rollback_failed")
    assert result.fingerprint == (fingerprint(db.source) if failure is None else None)
    assert db.events[:4] == ["locks", "forward SQL", "rollback", "close"]
    assert "commit" not in db.events
    if failure != "rollback_error":
        assert db.events[-1] == "read"


def test_adoption_before_commit_refusal_rolls_back_written_catalog(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=lambda conn: AdoptionError("maintenance_refused"),
    )
    assert (result.status, result.category, result.fingerprint) == (
        "rolled_back",
        "maintenance_refused",
        fingerprint(db.source),
    )
    assert db.durable == db.source
    assert db.events == ["locks", "forward SQL", "rollback", "close", "read"]


def test_adoption_mutation_rejects_unvalidated_sql_before_connect(monkeypatch):
    module = import_module("avelren.adoption_transaction")
    db = Database()
    attempts = []

    def connect(*args, **kwargs):
        attempts.append(True)
        raise psycopg.OperationalError("unexpected connection")

    monkeypatch.setattr(module.psycopg, "connect", connect)
    with pytest.raises(AdoptionError):
        module.run_mutation(
            "dsn",
            db.plan,
            direction="forward",
            before_write=lambda conn: None,
            before_commit=lambda conn: None,
        )
    assert db.events == []
    assert attempts == []


def test_adoption_mutation_rejects_unknown_direction_before_connect(monkeypatch):
    module = import_module("avelren.adoption_transaction")
    with pytest.raises(AdoptionError, match="mutation_direction"):
        module.run_mutation(
            "dsn",
            Database().plan,
            direction="unexpected",
            before_write=lambda conn: None,
            before_commit=lambda conn: None,
        )


def test_adoption_unexpected_callback_exception_requires_rollback_proof(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)

    def fail(conn):
        raise RuntimeError("private callback diagnostic")

    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=fail,
    )
    assert (result.status, result.category, result.fingerprint) == (
        "rolled_back",
        "pre_commit_failure",
        fingerprint(db.source),
    )
    assert db.events == ["locks", "forward SQL", "rollback", "close", "read"]
    assert "private callback diagnostic" not in repr(result)


def test_adoption_unexpected_commit_exception_is_unknown(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)

    def fail():
        db.events.append("commit")
        raise RuntimeError("private driver diagnostic")

    monkeypatch.setattr(db, "commit", fail)
    result = module.run_mutation(
        "dsn",
        db.plan,
        direction="forward",
        before_write=lambda conn: None,
        before_commit=lambda conn: None,
    )
    assert result.status == "commit_unknown"
    assert result.category == "commit_acknowledgement_unavailable"
    assert db.events == ["locks", "forward SQL", "commit", "close"]
    assert "private driver diagnostic" not in repr(result)


def test_adoption_unexpected_prewrite_exception_is_sanitized(monkeypatch):
    db = Database()
    module = engine(monkeypatch, db)

    def fail(conn):
        raise RuntimeError("sentinel-secret-callback")

    with pytest.raises(AdoptionError, match="pre_commit_failure") as error:
        module.run_mutation(
            "dsn",
            db.plan,
            direction="forward",
            before_write=fail,
            before_commit=lambda conn: None,
        )
    assert "sentinel-secret-callback" not in str(error.value)
    assert db.events == ["locks", "rollback", "close"]
