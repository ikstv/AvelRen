"""Production target binding against disposable PostgreSQL only."""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import psycopg
import pytest

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_preflight import acquire_adoption_locks, require_quiescent
from avelren.adoption_target import capture_target, verify_target


def test_adoption_target_matches_current_identity(database):
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        binding = capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
        identity = conn.execute(
            "SELECT system_identifier::text, current_database(), oid, session_user "
            "FROM pg_control_system(), pg_database WHERE datname = current_database()"
        ).fetchone()
        assert (
            binding.system_identifier,
            binding.database,
            binding.database_oid,
            binding.session_role,
        ) == identity
        verify_target(conn, binding)


@pytest.mark.parametrize("field", ["database_oid", "system_identifier", "session_role", "database"])
def test_adoption_target_refuses_changed_identity_before_mutation(database, field):
    with psycopg.connect(database("admin")) as conn:
        conn.execute("CREATE TEMP TABLE mutation_guard (value integer)")
        binding = capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
        changed = {
            "database_oid": binding.database_oid + 1,
            "system_identifier": str(int(binding.system_identifier) + 1),
            "session_role": "avelren_migrator",
            "database": "other",
        }[field]
        with pytest.raises(AdoptionError, match="target_mismatch"):
            verify_target(conn, replace(binding, **{field: changed}))
            conn.execute("INSERT INTO mutation_guard VALUES (1)")
        assert conn.execute("SELECT count(*) FROM mutation_guard").fetchone()[0] == 0


def test_adoption_target_denied_identity_read_refuses(database):
    # PostgreSQL grants this function to PUBLIC by default; deny it only in
    # this disposable database so the permission failure is real and explicit.
    with psycopg.connect(database("admin")) as admin:
        admin.execute("REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC")
    with psycopg.connect(database("collector")) as conn:
        with pytest.raises(AdoptionError, match="target_identity_read_failed"):
            capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)


def _pause_fixture_jobs(conn):
    # Only disposable fixture setup; the production helper never pauses jobs.
    conn.execute("SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs")


def test_adoption_quiescence_rejects_idle_session(database):
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        _pause_fixture_jobs(conn)
        require_quiescent(conn)
        with psycopg.connect(database("collector"), autocommit=True) as idle:
            idle.execute("SELECT 1")
            with pytest.raises(AdoptionError, match="active_sessions"):
                require_quiescent(conn)


def test_adoption_quiescence_jobs(database):
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        assert conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='timescaledb'"
        ).fetchone() == ("2.30.1",)
        with pytest.raises(AdoptionError, match="timescale_jobs"):
            require_quiescent(conn)
        _pause_fixture_jobs(conn)
        require_quiescent(conn)


def test_adoption_quiescence_repeated_check_refreshes_activity(database):
    with psycopg.connect(database("admin"), autocommit=True) as setup:
        _pause_fixture_jobs(setup)
    with psycopg.connect(database("admin")) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        require_quiescent(conn)
        with psycopg.connect(database("collector"), autocommit=True) as idle:
            idle.execute("SELECT 1")
            with pytest.raises(AdoptionError, match="active_sessions"):
                require_quiescent(conn)


@pytest.mark.parametrize("status", ["Running", "Unknown", None])
def test_adoption_quiescence_jobs_incomplete_or_unknown_view_refuses(database, status):
    # Fault injection belongs only in the disposable fixture, never the helper.
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        _pause_fixture_jobs(conn)
        conn.execute("ALTER VIEW timescaledb_information.job_stats RENAME TO fixture_job_stats")
        conn.execute(
            "CREATE VIEW timescaledb_information.job_stats AS "
            "SELECT job_id, NULL::text AS job_status FROM timescaledb_information.fixture_job_stats"
        )
        if status is not None:
            from psycopg import sql

            conn.execute(
                sql.SQL(
                    "CREATE OR REPLACE VIEW timescaledb_information.job_stats AS "
                    "SELECT job_id, {}::text AS job_status "
                    "FROM timescaledb_information.fixture_job_stats"
                ).format(sql.Literal(status))
            )
        with pytest.raises(AdoptionError, match="timescale_jobs"):
            require_quiescent(conn)


def test_adoption_quiescence_denied_job_metadata_refuses(database):
    with psycopg.connect(database("admin"), autocommit=True) as setup:
        _pause_fixture_jobs(setup)
        setup.execute("REVOKE SELECT ON timescaledb_information.jobs FROM PUBLIC")
    with psycopg.connect(database("collector"), autocommit=True) as conn:
        with pytest.raises(AdoptionError, match="quiescence_read_failed"):
            require_quiescent(conn)


def _hold_advisory(conn):
    conn.execute(
        "SELECT pg_advisory_lock(hashtextextended(current_database() || ':avelren-adoption-016',0))"
    )


def test_adoption_advisory_wait_is_bounded(database):
    with psycopg.connect(database("admin"), autocommit=True) as holder:
        _pause_fixture_jobs(holder)
        before = holder.execute(
            "SELECT relacl FROM pg_class WHERE oid='public.devices'::regclass"
        ).fetchone()
        _hold_advisory(holder)
        with psycopg.connect(database("admin")) as conn:
            started = time.monotonic()
            with pytest.raises(AdoptionError, match="adoption_lock_timeout"):
                acquire_adoption_locks(conn, conn.info.dbname, timeout_ms=150)
            assert time.monotonic() - started < 3
        assert (
            holder.execute(
                "SELECT relacl FROM pg_class WHERE oid='public.devices'::regclass"
            ).fetchone()
            == before
        )
        assert holder.execute("SELECT 1").fetchone() == (1,)


def test_adoption_advisory_object_wait_is_bounded(database):
    with psycopg.connect(database("admin")) as holder:
        holder.execute("LOCK TABLE devices IN ACCESS SHARE MODE")
        with psycopg.connect(database("admin")) as conn:
            started = time.monotonic()
            with pytest.raises(AdoptionError, match="adoption_lock_timeout"):
                acquire_adoption_locks(conn, conn.info.dbname, timeout_ms=150)
            assert time.monotonic() - started < 3
        assert holder.execute("SELECT 1").fetchone() == (1,)


def _wait_for_advisory_wait(holder, pid):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        waiting = holder.execute(
            "SELECT wait_event FROM pg_stat_activity WHERE pid=%s", (pid,)
        ).fetchone()
        if waiting == ("advisory",):
            return
        time.sleep(0.02)
    pytest.fail("adoption did not wait on the advisory lock")


def _lock_then_check(conn):
    acquire_adoption_locks(conn, conn.info.dbname, timeout_ms=3000)
    require_quiescent(conn)


def test_adoption_advisory_session_appearing_during_wait_refuses(database):
    with psycopg.connect(database("admin"), autocommit=True) as holder:
        _pause_fixture_jobs(holder)
        _hold_advisory(holder)
        with (
            psycopg.connect(database("admin")) as conn,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(_lock_then_check, conn)
            _wait_for_advisory_wait(holder, conn.info.backend_pid)
            with psycopg.connect(database("collector"), autocommit=True) as new_session:
                new_session.execute("SELECT 1")
                holder.close()
                with pytest.raises(AdoptionError, match="active_sessions"):
                    future.result(timeout=5)


def test_adoption_advisory_snapshot_starts_after_wait_and_locks_objects(database):
    with psycopg.connect(database("admin"), autocommit=True) as holder:
        _pause_fixture_jobs(holder)
        _hold_advisory(holder)
        with (
            psycopg.connect(database("admin")) as conn,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(
                acquire_adoption_locks, conn, conn.info.dbname, timeout_ms=3000
            )
            _wait_for_advisory_wait(holder, conn.info.backend_pid)
            holder.execute("INSERT INTO countries(id,name) VALUES (999999,'Snapshot after wait')")
            holder.close()
            future.result(timeout=5)
            assert conn.execute("SHOW transaction_isolation").fetchone() == ("repeatable read",)
            assert conn.execute("SELECT name FROM countries WHERE id=999999").fetchone() == (
                "Snapshot after wait",
            )
            assert conn.execute(
                "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() "
                "AND mode='AccessExclusiveLock' AND relation='public.devices'::regclass"
            ).fetchone() == (1,)
