"""Shared ownership/ACL transaction; evidence and runtime policy belong to callers."""

from dataclasses import dataclass

import psycopg

from .adoption_inventory import AdoptionError, _capture_catalog, capture, fingerprint
from .adoption_plan import AdoptionPlan, decode_plan, encode_plan
from .adoption_preflight import acquire_adoption_locks

READ_OPTIONS = "-c default_transaction_read_only=on -c statement_timeout=30000"
WRITE_OPTIONS = (
    "-c default_transaction_read_only=off -c lock_timeout=10000 -c statement_timeout=30000"
)


@dataclass(frozen=True)
class TransactionOutcome:
    status: str
    category: str | None
    fingerprint: str | None


def read_snapshot(dsn):
    with psycopg.connect(dsn, connect_timeout=10, options=READ_OPTIONS) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return capture(conn)


def _callback(callback, conn):
    result = callback(conn)
    if isinstance(result, AdoptionError):
        raise result
    if result is not None:
        raise AdoptionError("mutation_callback_contract")


def run_mutation(
    dsn: str, plan: AdoptionPlan, *, direction: str, before_write, before_commit
) -> TransactionOutcome:
    """Run one mutation, never retrying COMMIT or compensating after COMMIT.

    A categorical refusal before the first mutation attempt is raised only after
    confirmed rollback/close. Foreign drift is preserved, not treated as our write.
    Once a statement is attempted, rollback also needs separate read-only proof.
    """
    if direction not in {"forward", "inverse"}:
        raise AdoptionError("mutation_direction")
    plan = decode_plan(encode_plan(plan))
    source = fingerprint(plan.before if direction == "forward" else plan.expected)
    target = fingerprint(plan.expected if direction == "forward" else plan.before)
    statements = plan.forward if direction == "forward" else plan.inverse
    try:
        conn = psycopg.connect(dsn, connect_timeout=10, options=WRITE_OPTIONS)
    except Exception:
        raise AdoptionError("mutation_connection_unavailable") from None
    close_attempted = False

    def close():
        nonlocal close_attempted
        close_attempted = True
        try:
            conn.close()
            return True
        except Exception:
            return False

    mutation_started = False
    try:
        try:
            acquire_adoption_locks(conn, plan.before.database)
            _callback(before_write, conn)
            if fingerprint(_capture_catalog(conn)) != source:
                raise AdoptionError("plan_drift" if direction == "forward" else "inverse_drift")
            for statement in statements:
                # An attempted statement can have effects even if its acknowledgement fails.
                mutation_started = True
                conn.execute(statement)
            if fingerprint(_capture_catalog(conn)) != target:
                raise AdoptionError(direction + "_verification")
            _callback(before_commit, conn)
        except Exception as exc:
            category = exc.category if isinstance(exc, AdoptionError) else "pre_commit_failure"
            rollback_ok = True
            try:
                conn.rollback()
            except Exception:
                rollback_ok = False
            closed = close()
            if not rollback_ok or not closed:
                return TransactionOutcome("rollback_failed", "pre_commit_unverified", None)
            if not mutation_started:
                raise AdoptionError(category) from None
            try:
                restored = fingerprint(read_snapshot(dsn))
            except Exception:
                return TransactionOutcome("rollback_failed", "pre_commit_unverified", None)
            if restored != source:
                return TransactionOutcome("rollback_failed", "pre_commit_unverified", restored)
            return TransactionOutcome("rolled_back", category, restored)
        try:
            conn.commit()
        except Exception:
            # Explicit close precedes all unwinding; no context manager can retry
            # COMMIT or attempt rollback against an ambiguous server outcome.
            close()
            return TransactionOutcome("commit_unknown", "commit_acknowledgement_unavailable", None)
        if not close():
            return TransactionOutcome("commit_unknown", "connection_close_unavailable", None)
        return TransactionOutcome("committed", None, target)
    finally:
        if not close_attempted:
            close()
