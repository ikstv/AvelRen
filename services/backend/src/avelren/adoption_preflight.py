"""Production quiescence and bounded lock preflight."""

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row

from . import privilege_gate
from .adoption_inventory import AdoptionError

_SCHEDULER = "TimescaleDB Background Worker Scheduler"


def require_quiescent(conn) -> None:
    """Check fresh activity and fully paused jobs, without changing jobs/sessions."""
    try:
        with conn.cursor(row_factory=tuple_row) as cursor:
            # PG16 caches activity within a transaction. Discard only this
            # connection's statistics snapshot before each repeated check.
            cursor.execute("SELECT pg_catalog.pg_stat_clear_snapshot()")
            cursor.execute(
                "SELECT pid, backend_type, application_name, state "
                "FROM pg_catalog.pg_stat_activity WHERE datname = pg_catalog.current_database() "
                "AND pid <> pg_catalog.pg_backend_pid()"
            )
            sessions = cursor.fetchall()
            cursor.execute(
                "SELECT 1 FROM pg_catalog.pg_prepared_xacts "
                "WHERE database = pg_catalog.current_database()"
            )
            prepared = cursor.fetchall()
            cursor.execute(
                "SELECT j.job_id, j.scheduled, s.job_status "
                "FROM timescaledb_information.jobs AS j FULL JOIN "
                "timescaledb_information.job_stats AS s ON s.job_id = j.job_id"
            )
            jobs = cursor.fetchall()
    except psycopg.Error:
        raise AdoptionError("quiescence_read_failed") from None
    if any(row[1:] != (_SCHEDULER, _SCHEDULER, "idle") for row in sessions):
        raise AdoptionError("active_sessions")
    if prepared:
        raise AdoptionError("prepared_transactions")
    seen = set()
    for job_id, scheduled, status in jobs:
        if (
            type(job_id) is not int
            or job_id <= 0
            or job_id in seen
            or scheduled is not False
            or status != "Paused"
        ):
            raise AdoptionError("timescale_jobs")
        seen.add(job_id)


def acquire_adoption_locks(conn, database: str, *, timeout_ms: int = 10000) -> None:
    """Lock on a dedicated idle connection, waiting before taking an RR snapshot.

    Leaves a repeatable-read transaction with object locks and a session advisory
    lock held until the dedicated connection closes. The caller supplies its
    quiescence policy after these locks and before capture/mutation.
    """
    if type(timeout_ms) is not int or not 0 < timeout_ms <= 10000:
        raise AdoptionError("lock_timeout")
    if conn.info.dbname != database:
        raise AdoptionError("database_identity")
    if conn.info.transaction_status != TransactionStatus.IDLE:
        # Never commit or roll back a caller's identity-read transaction silently.
        raise AdoptionError("adoption_lock_transaction")
    try:
        conn.autocommit = True
        original_timeout = conn.execute("SHOW statement_timeout").fetchone()[0]
        conn.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout_ms),))
        try:
            conn.execute(
                "SELECT pg_advisory_lock(hashtextextended("
                "current_database() || ':avelren-adoption-016',0))"
            )
        finally:
            conn.execute("SELECT set_config('statement_timeout', %s, false)", (original_timeout,))
        conn.autocommit = False
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        for setting in ("lock_timeout", "statement_timeout"):
            conn.execute(
                sql.SQL("SET LOCAL {} = {}").format(
                    sql.Identifier(setting), sql.Literal(timeout_ms)
                )
            )
        for name in sorted(set(privilege_gate.TABLES) - {"observations_hourly"}):
            conn.execute(
                sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                    sql.Identifier("public", name)
                )
            )
    except (psycopg.errors.QueryCanceled, psycopg.errors.LockNotAvailable):
        raise AdoptionError("adoption_lock_timeout") from None
    except psycopg.Error:
        raise AdoptionError("adoption_lock_failed") from None
