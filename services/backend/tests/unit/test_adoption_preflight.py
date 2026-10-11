"""Fail-closed quiescence when catalog metadata cannot be trusted."""

from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_preflight import acquire_adoption_locks, require_quiescent


class CatalogConnection:
    """Only catalog reads; impossible metadata needs no real server mutation."""

    def __init__(self, *, sessions=(), prepared=(), jobs=((1, False, "Paused"),), denied=None):
        self.rows = [sessions, prepared, jobs]
        self.denied = denied

    @contextmanager
    def cursor(self, **kwargs):
        yield self

    def execute(self, query, params=None):
        if self.denied is not None:
            raise self.denied("secret query/config")
        if query == "SELECT pg_catalog.pg_stat_clear_snapshot()":
            return
        self.result = self.rows.pop(0)

    def fetchall(self):
        return self.result


def test_adoption_quiescence_prepared_transaction_refuses():
    with pytest.raises(AdoptionError, match="prepared_transactions"):
        require_quiescent(CatalogConnection(prepared=((1,),)))


@pytest.mark.parametrize(
    "denied", [psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable]
)
def test_adoption_quiescence_unreadable_metadata_refuses_without_sensitive_diagnostics(denied):
    with pytest.raises(AdoptionError) as failure:
        require_quiescent(CatalogConnection(denied=denied))
    assert str(failure.value) == "quiescence_read_failed"
    assert failure.value.__cause__ is None


@pytest.mark.parametrize(
    "job",
    [
        (1, True, "Scheduled"),
        (1, False, "Running"),
        (1, False, None),
        (None, False, "Paused"),
        (1, None, "Paused"),
        (1, False, "Unknown"),
        (1, False, "Scheduled"),
    ],
)
def test_adoption_quiescence_jobs_unknown_or_active_metadata_refuses(job):
    with pytest.raises(AdoptionError, match="timescale_jobs"):
        require_quiescent(CatalogConnection(jobs=(job,)))


@pytest.mark.parametrize(
    "session",
    [
        pytest.param((42, "autovacuum worker", "", "active"), id="active-autovacuum"),
        (42, "client backend", "TimescaleDB Background Worker Scheduler", "idle"),
        (42, "unknown writer", "TimescaleDB Background Worker Scheduler", "idle"),
        (42, "TimescaleDB Background Worker Scheduler", "other", "idle"),
        (
            42,
            "TimescaleDB Background Worker Scheduler",
            "TimescaleDB Background Worker Scheduler",
            "active",
        ),
        (42, None, None, None),
    ],
)
def test_adoption_quiescence_unsupported_background_writer_refuses(session):
    with pytest.raises(AdoptionError, match="active_sessions"):
        require_quiescent(CatalogConnection(sessions=(session,)))


def test_adoption_quiescence_paused_jobs_and_known_idle_scheduler_pass():
    require_quiescent(
        CatalogConnection(
            sessions=(
                (
                    42,
                    "TimescaleDB Background Worker Scheduler",
                    "TimescaleDB Background Worker Scheduler",
                    "idle",
                ),
            )
        )
    )


@pytest.mark.parametrize("timeout", [0, -1, True, "100", 10001])
def test_adoption_advisory_invalid_timeout_refuses(timeout):
    with pytest.raises(AdoptionError, match="lock_timeout"):
        acquire_adoption_locks(None, "avelren", timeout_ms=timeout)


def test_adoption_advisory_wrong_database_refuses_before_sql():
    conn = SimpleNamespace(info=SimpleNamespace(dbname="other"))
    with pytest.raises(AdoptionError, match="database_identity"):
        acquire_adoption_locks(conn, "avelren")


@pytest.mark.parametrize("status", [TransactionStatus.INTRANS, TransactionStatus.INERROR])
def test_adoption_advisory_existing_transaction_refuses_without_committing_or_rolling_back(status):
    conn = SimpleNamespace(info=SimpleNamespace(dbname="avelren", transaction_status=status))
    with pytest.raises(AdoptionError, match="adoption_lock_transaction"):
        acquire_adoption_locks(conn, "avelren")
