"""Production target binding against disposable PostgreSQL only."""

import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_preflight import acquire_adoption_locks, require_quiescent
from avelren.adoption_target import capture_target, verify_target


@pytest.fixture
def production_case(database, tmp_path, monkeypatch, request):
    from avelren import adoption_production as production
    from avelren.adoption_operation import make_operation, write_operation
    from avelren.adoption_operator import Confirmation
    from avelren.adoption_plan import build_plan
    from avelren.adoption_transaction import read_snapshot

    dsn = database("admin")
    if getattr(request, "param", False):
        from psycopg import sql

        from avelren.privilege_gate import SEQUENCES, TABLES

        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'Synthetic',1)"
            )
            conn.execute(
                "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,"
                "is_paused,wait_time_status) VALUES(now()-interval '14 days',17,3600,20,"
                "false,'reported'),(now()-interval '13 days',17,7200,40,false,'reported')"
            )
            conn.execute(
                "CALL refresh_continuous_aggregate('observations_hourly',"
                "now()-interval '20 days',now())"
            )
            conn.execute(
                "SELECT compress_chunk(show_chunks('observations'),if_not_compressed=>true)"
            )
        with psycopg.connect(dsn) as conn:
            for name in TABLES:
                kind = "MATERIALIZED VIEW" if name == "observations_hourly" else "TABLE"
                conn.execute(
                    sql.SQL("ALTER " + kind + " {} OWNER TO avelren_admin").format(
                        sql.Identifier("public", name)
                    )
                )
            for name in SEQUENCES:
                conn.execute(
                    sql.SQL("ALTER SEQUENCE {} OWNER TO avelren_admin").format(
                        sql.Identifier("public", name)
                    )
                )
    with psycopg.connect(dsn) as conn:
        _pause_fixture_jobs(conn)
        conn.execute("ALTER TABLE devices OWNER TO avelren_admin")
        conn.execute("GRANT SELECT ON devices TO PUBLIC")
        binding = capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
    plan = build_plan(read_snapshot(dsn))
    manifest = make_operation(binding, plan)
    directory = tmp_path / "production-evidence"
    write_operation(directory, manifest)
    context = production.MaintenanceContext(
        manifest.operation_id,
        manifest.target_digest,
        manifest.plan_digest,
        binding.runtime_digest,
        "quiescent",
    )

    class Runtime:
        calls = 0
        on_verify = None

        def verify(self, context, operation):
            assert operation == manifest
            self.calls += 1
            if self.on_verify:
                self.on_verify(self.calls)

        def checkout_roots(self):
            return (Path(__file__).resolve().parents[4],)

    runtime = Runtime()

    def call(inverse=False, confirmation=None):
        # Validate the *entire* disposable DSN before temporarily removing the
        # forbidden environment; production code has no fixture mode/bypass.
        parsed = conninfo_to_dict(dsn)
        assert os.environ.get("AVELREN_DATABASE_TEST") == "1"
        assert re.fullmatch(r"avelren_case_[0-9a-f]{32}_test", parsed["dbname"])
        assert parsed == {
            "user": "avelren_admin",
            "password": "ci-only",
            "host": "test-db",
            "port": "5432",
            "dbname": binding.database,
        }
        action = "INVERSE" if inverse else "ADOPT"
        confirmation = confirmation or Confirmation(
            action, manifest.operation_id, manifest.target_digest, manifest.plan_digest
        )
        function = production.inverse_production if inverse else production.apply_production
        with monkeypatch.context() as isolated:
            isolated.delenv("AVELREN_DATABASE_TEST")
            isolated.delenv("AVELREN_ADOPTION_TEST_FAILPOINT", raising=False)
            return function(dsn, binding, plan, directory, context, confirmation, runtime)

    return SimpleNamespace(
        call=call,
        runtime=runtime,
        plan=plan,
        manifest=manifest,
        directory=directory,
        dsn=dsn,
        production=production,
        read=lambda: read_snapshot(dsn),
    )


def _content_digest(dsn):
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
        content = [
            conn.execute(query).fetchall()
            for query in (
                "SELECT * FROM observations ORDER BY time,checkpoint_id",
                "SELECT * FROM observations_hourly ORDER BY bucket,checkpoint_id",
                "SELECT * FROM schema_migrations ORDER BY version",
                "SELECT pg_get_functiondef(oid) FROM pg_proc WHERE proname IN "
                "('activate_approved_admin','prune_inactive_devices',"
                "'activate_admin_after_pin','discard_disabled_surge_alert') ORDER BY oid",
            )
        ]
    return hashlib.sha256(repr(content).encode()).hexdigest()


@pytest.mark.parametrize("production_case", [True], indirect=True)
def test_adoption_production_accepts_then_explicitly_inverts(production_case):
    from avelren.adoption_inventory import fingerprint
    from avelren.adoption_operation import verify_receipt

    case = production_case
    data_digest = _content_digest(case.dsn)
    assert any(row["kind"] == "chunk" for row in case.plan.before.sections["topology"])
    result = case.call()
    assert result.status == "adopted"
    assert fingerprint(case.read()) == fingerprint(case.plan.expected)
    assert _content_digest(case.dsn) == data_digest
    for phase in ("apply-intent", "committed", "accepted"):
        verify_receipt(case.directory, phase, case.manifest)
    assert case.call().status == "already_target"
    assert case.call(inverse=True).status == "rolled_back"
    assert fingerprint(case.read()) == fingerprint(case.plan.before)
    assert _content_digest(case.dsn) == data_digest
    for phase in ("inverse-intent", "inverse-committed", "inverse-accepted"):
        verify_receipt(case.directory, phase, case.manifest)
    with pytest.raises(AdoptionError, match="incomplete_evidence"):
        case.call(inverse=True)


def test_adoption_production_rechecks_runtime_under_locks(production_case):
    from avelren.adoption_inventory import fingerprint

    case = production_case

    def drift(calls):
        if calls == 2:
            raise AdoptionError("runtime_drift")

    case.runtime.on_verify = drift
    with pytest.raises(AdoptionError, match="runtime_drift"):
        case.call()
    assert case.runtime.calls == 2
    assert fingerprint(case.read()) == fingerprint(case.plan.before)
    assert not (case.directory / "production-apply-intent.json").exists()


@pytest.mark.parametrize("inverse", [False, True])
def test_adoption_production_sql_failure_is_proven(production_case, monkeypatch, inverse):
    from avelren.adoption_inventory import fingerprint

    case = production_case
    if inverse:
        assert case.call().status == "adopted"
    original = psycopg.Connection.execute
    statements = case.plan.inverse if inverse else case.plan.forward

    def execute(conn, query, *args, **kwargs):
        if query == statements[-1]:
            return original(conn, "SELECT missing_production_fixture_function()")
        return original(conn, query, *args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(psycopg.Connection, "execute", execute)
        result = case.call(inverse=inverse)
    assert result.status == ("rollback_failed" if inverse else "rolled_back")
    assert result.category == "pre_commit_failure"
    assert fingerprint(case.read()) == fingerprint(
        case.plan.expected if inverse else case.plan.before
    )
    assert not (
        case.directory
        / ("production-inverse-committed.json" if inverse else "production-committed.json")
    ).exists()
    with pytest.raises(AdoptionError, match="incomplete_evidence"):
        case.call(inverse=inverse)


@pytest.mark.parametrize("inverse", [False, True])
@pytest.mark.parametrize("server_committed", [False, True])
def test_adoption_production_commit_ack_loss(
    production_case, monkeypatch, inverse, server_committed, capsys
):
    from avelren.adoption_inventory import fingerprint

    case = production_case
    if inverse:
        assert case.call().status == "adopted"
    original = psycopg.Connection.commit
    commits, rollbacks = [], []

    def lost_ack(conn):
        if "default_transaction_read_only=off" in conn.info.options:
            commits.append(conn)
            if server_committed:
                original(conn)
            raise psycopg.OperationalError("password=DO_NOT_EXPOSE")
        return original(conn)

    def rollback(conn):
        rollbacks.append(conn)
        raise RuntimeError("ambiguous commit cannot be rolled back")

    with monkeypatch.context() as injected:
        injected.setattr(psycopg.Connection, "commit", lost_ack)
        injected.setattr(psycopg.Connection, "rollback", rollback)
        result = case.call(inverse=inverse)
    assert result.status == "commit_unknown"
    assert result.category == "commit_acknowledgement_unavailable"
    assert result.after_fingerprint is None
    assert len(commits) == 1 and commits[0].closed
    assert not rollbacks
    assert fingerprint(case.read()) == fingerprint(
        case.plan.expected if server_committed != inverse else case.plan.before
    )
    assert "DO_NOT_EXPOSE" not in repr(result) + "".join(capsys.readouterr())


@pytest.mark.parametrize(
    "phase", ["committed", "accepted", "inverse-committed", "inverse-accepted"]
)
def test_adoption_production_receipt_fsync_loss_is_unknown(production_case, monkeypatch, phase):
    from avelren import adoption_evidence
    from avelren.adoption_inventory import fingerprint

    case = production_case
    inverse = phase.startswith("inverse")
    if inverse:
        assert case.call().status == "adopted"
    write = case.production.write_receipt

    def unavailable(*args):
        raise OSError("password=DO_NOT_EXPOSE")

    def receipt(directory, current, manifest, **kwargs):
        if current == phase:
            with monkeypatch.context() as io:
                io.setattr(adoption_evidence.os, "fsync", unavailable)
                return write(directory, current, manifest, **kwargs)
        return write(directory, current, manifest, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(case.production, "write_receipt", receipt)
        result = case.call(inverse=inverse)
    assert result.status == "commit_unknown"
    assert result.after_fingerprint is None
    assert not (case.directory / f"production-{phase}.json").exists()
    assert fingerprint(case.read()) == fingerprint(
        case.plan.before if inverse else case.plan.expected
    )
    with pytest.raises(AdoptionError, match="incomplete_evidence"):
        case.call(inverse=inverse)
    if phase == "committed":
        with pytest.raises(AdoptionError, match="incomplete_evidence"):
            case.call(inverse=True)


@pytest.mark.parametrize("unavailable", [False, True])
def test_adoption_production_acceptance_never_automatically_inverts(
    production_case, monkeypatch, unavailable
):
    from avelren.adoption_inventory import fingerprint
    from avelren.adoption_operator import Confirmation

    case = production_case

    def audit(*args):
        if unavailable:
            raise RuntimeError("password=DO_NOT_EXPOSE")
        return ["confirmed gate failure"]

    with monkeypatch.context() as injected:
        injected.setattr(case.production.privilege_gate, "audit", audit)
        result = case.call()
    assert (result.status, result.category) == (
        ("commit_unknown", "post_commit_unverified")
        if unavailable
        else ("rollback_failed", "acceptance_failed")
    )
    assert fingerprint(case.read()) == fingerprint(case.plan.expected)
    assert not (case.directory / "production-inverse-intent.json").exists()
    assert not (case.directory / "production-accepted.json").exists()
    assert (case.directory / "production-committed.json").exists()
    wrong_action = Confirmation(
        "ADOPT", case.manifest.operation_id, case.manifest.target_digest, case.manifest.plan_digest
    )
    with pytest.raises(AdoptionError, match="operator_confirmation"):
        case.call(inverse=True, confirmation=wrong_action)
    assert case.call(inverse=True).status == "rolled_back"
    assert fingerprint(case.read()) == fingerprint(case.plan.before)


@pytest.mark.parametrize("phase", ["apply-intent", "committed", "accepted"])
def test_adoption_production_corrupt_receipt_refuses_before_connect(
    production_case, monkeypatch, phase
):
    case = production_case
    assert case.call().status == "adopted"
    (case.directory / f"production-{phase}.json").write_bytes(b"{}")
    connected = []

    def denied(*args, **kwargs):
        connected.append(True)
        raise RuntimeError("unexpected connection")

    with monkeypatch.context() as injected:
        injected.setattr(psycopg, "connect", denied)
        with pytest.raises(AdoptionError, match="receipt_format"):
            case.call()
        with pytest.raises(AdoptionError, match="receipt_format"):
            case.call(inverse=True)
    assert not connected


@pytest.mark.parametrize("inverse", [False, True])
def test_adoption_production_locked_drift_preserves_foreign_grant(
    production_case, monkeypatch, inverse
):
    case = production_case
    if inverse:
        assert case.call().status == "adopted"
    run = case.production.run_mutation

    def mutation(*args, **kwargs):
        with psycopg.connect(case.dsn) as conn:
            conn.execute("GRANT DELETE ON devices TO avelren_api")
        return run(*args, **kwargs)

    with monkeypatch.context() as injected:
        injected.setattr(case.production, "run_mutation", mutation)
        with pytest.raises(AdoptionError, match="inverse_drift" if inverse else "plan_drift"):
            case.call(inverse=inverse)
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute(
            "SELECT has_table_privilege('avelren_api','devices','DELETE')"
        ).fetchone() == (True,)
    assert not (
        case.directory
        / ("production-inverse-intent.json" if inverse else "production-apply-intent.json")
    ).exists()


@pytest.mark.parametrize("inverse", [False, True])
def test_adoption_production_post_commit_capture_loss(production_case, monkeypatch, inverse):
    case = production_case
    if inverse:
        assert case.call().status == "adopted"
    capture = case.production.capture
    calls = 0

    def unavailable(conn):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise psycopg.OperationalError("password=DO_NOT_EXPOSE")
        return capture(conn)

    with monkeypatch.context() as injected:
        injected.setattr(case.production, "capture", unavailable)
        result = case.call(inverse=inverse)
    assert (result.status, result.category) == ("commit_unknown", "post_commit_unverified")
    assert result.after_fingerprint is None


@pytest.mark.parametrize("inverse", [False, True])
def test_adoption_production_post_commit_evidence_drift_is_unknown(production_case, inverse):
    case = production_case
    if inverse:
        assert case.call().status == "adopted"
    start = case.runtime.calls

    def corrupt(calls):
        if calls == start + 4:
            (case.directory / "production-committed.json").write_bytes(b"{}")

    case.runtime.on_verify = corrupt
    result = case.call(inverse=inverse)
    assert (result.status, result.category) == ("commit_unknown", "post_commit_unverified")
    assert not (
        case.directory
        / ("production-inverse-accepted.json" if inverse else "production-accepted.json")
    ).exists()


def test_adoption_production_inverse_lost_authority_before_commit_rolls_back(production_case):
    from avelren.adoption_inventory import fingerprint

    case = production_case
    assert case.call().status == "adopted"
    start = case.runtime.calls

    def corrupt(calls):
        if calls == start + 3:
            (case.directory / "production-committed.json").write_bytes(b"{}")

    case.runtime.on_verify = corrupt
    result = case.call(inverse=True)
    assert result.status == "rollback_failed"
    assert fingerprint(case.read()) == fingerprint(case.plan.expected)
    assert not (case.directory / "production-inverse-committed.json").exists()


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
