"""Історія міграцій має відповідати файлам і фізичній схемі."""

import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import psycopg
import pytest

from avelren import migrate, schema_verify

from .conftest import MIGRATIONS


@pytest.mark.parametrize("database", [9], indirect=True)
def test_valid_009_upgrades_to_candidate_without_rewriting_history(database):
    with psycopg.connect(database("migrator")) as conn:
        before = conn.execute(
            "SELECT version,sha256,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert len(before) == 9
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(database("migrator")) as conn:
        after = conn.execute(
            "SELECT version,sha256,applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert len(after) == 14
        assert after[:9] == before


def test_history_hashes_and_idempotency(database):
    with psycopg.connect(database("migrator")) as conn:
        before = conn.execute(
            "SELECT version, sha256, applied_at FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected = [
            (p.stem, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(MIGRATIONS.glob("*.sql"))
        ]
        assert [(version, digest) for version, digest, _ in before] == expected
        assert schema_verify.verify(conn, MIGRATIONS) == []
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(database("migrator")) as conn:
        assert (
            conn.execute(
                "SELECT version, sha256, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
            == before
        )


def test_changed_file_is_rejected(database, tmp_path):
    files = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, files)
    changed = files / "004_alerts.sql"
    changed.write_bytes(changed.read_bytes() + b"\n-- changed test copy\n")
    assert migrate.run(files) == 1


@pytest.mark.parametrize(
    "damage",
    [
        "DELETE FROM schema_migrations WHERE version = '004_alerts'",
        "INSERT INTO schema_migrations(version,sha256) VALUES ('999_unknown','x')",
        "TRUNCATE schema_migrations",
        "ALTER TABLE devices DROP COLUMN secret_hash",
    ],
)
def test_damaged_history_or_schema_is_rejected(database, damage):
    with psycopg.connect(database("admin")) as conn:
        conn.execute(damage)
    with psycopg.connect(database("admin")) as conn:
        before = conn.execute(
            "SELECT version,sha256 FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert migrate.run(MIGRATIONS) == 1
    with psycopg.connect(database("admin")) as conn:
        assert (
            conn.execute("SELECT version,sha256 FROM schema_migrations ORDER BY version").fetchall()
            == before
        )


def test_admin_function_is_not_owned_by_superuser(database):
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute("""
            SELECT r.rolname, r.rolsuper, p.prosecdef, p.proconfig
            FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
            WHERE p.oid = 'public.activate_approved_admin(uuid)'::regprocedure
        """).fetchone() == ("avelren_migrator", False, True, ["search_path=pg_catalog, pg_temp"])

def test_pin_rebind_function_is_migrator_owned_and_narrowly_granted(database):
    with psycopg.connect(database("admin")) as conn:
        row = conn.execute("""
            SELECT r.rolname, r.rolsuper, p.prosecdef, p.proconfig,
                   has_function_privilege('avelren_api', p.oid, 'EXECUTE'),
                   has_function_privilege('avelren_backup', p.oid, 'EXECUTE'),
                   EXISTS (SELECT 1 FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
            FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
            WHERE p.oid = to_regprocedure('public.activate_admin_after_pin(uuid)')
        """).fetchone()
        assert row == (
            "avelren_migrator", False, True, ["search_path=pg_catalog, pg_temp"],
            True, False, False,
        )


def test_pin_rebind_moves_single_admin_and_requires_token(database):
    with psycopg.connect(database("admin")) as conn:
        old = conn.execute(
            "INSERT INTO devices(fcm_token) VALUES (%s) RETURNING id",
            ("synthetic-" + "a" * 32,),
        ).fetchone()[0]
        new = conn.execute(
            "INSERT INTO devices(fcm_token) VALUES (%s) RETURNING id",
            ("synthetic-" + "b" * 32,),
        ).fetchone()[0]
        no_token = conn.execute("INSERT INTO devices DEFAULT VALUES RETURNING id").fetchone()[0]
        conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (old,))
        conn.execute(
            "UPDATE admin_access SET approved_device_id=%s, pin_hash='test' WHERE singleton",
            (old,),
        )
    with psycopg.connect(database("api"), autocommit=True) as api:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("SELECT activate_admin_after_pin(%s::uuid)", (no_token,))
        api.execute("SELECT activate_admin_after_pin(%s::uuid)", (new,))
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute(
            "SELECT approved_device_id FROM admin_access WHERE singleton"
        ).fetchone()[0] == new
        assert conn.execute("SELECT id FROM devices WHERE is_admin").fetchall() == [(new,)]


def test_pin_rebind_refuses_global_and_installation_locks(database):
    with psycopg.connect(database("admin")) as conn:
        candidate = conn.execute(
            "INSERT INTO devices(fcm_token) VALUES (%s) RETURNING id",
            ("synthetic-" + "c" * 32,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE admin_access SET pin_hash='test', failures=3, "
            "locked_until=now()+interval '30 days' WHERE singleton"
        )
    with psycopg.connect(database("api"), autocommit=True) as api:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("SELECT activate_admin_after_pin(%s::uuid)", (candidate,))
    with psycopg.connect(database("admin")) as conn:
        conn.execute("UPDATE admin_access SET failures=0, locked_until=NULL")
        conn.execute(
            "UPDATE devices SET admin_blocked_until=now()+interval '1 day' WHERE id=%s",
            (candidate,),
        )
    with psycopg.connect(database("api"), autocommit=True) as api:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("SELECT activate_admin_after_pin(%s::uuid)", (candidate,))
    with psycopg.connect(database("admin")) as conn:
        assert conn.execute("SELECT approved_device_id FROM admin_access").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM devices WHERE is_admin").fetchone()[0] == 0


@pytest.mark.parametrize("database", [13], indirect=True)
def test_pin_rebind_is_absent_on_013_and_prefix_contract_remains_valid(database):
    with psycopg.connect(database("migrator")) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        assert len(versions) == 13
        assert schema_verify.verify_contract(conn, versions) == []
        assert conn.execute(
            "SELECT to_regprocedure('public.activate_admin_after_pin(uuid)')"
        ).fetchone()[0] is None


def test_concurrent_pin_rebinds_leave_exactly_one_admin(database):
    with psycopg.connect(database("admin")) as conn:
        candidates = [
            conn.execute(
                "INSERT INTO devices(fcm_token) VALUES (%s) RETURNING id",
                (f"synthetic-concurrent-{index}",),
            ).fetchone()[0]
            for index in range(2)
        ]
        conn.execute("UPDATE admin_access SET pin_hash='test' WHERE singleton")
    barrier = Barrier(2)

    def activate(candidate):
        with psycopg.connect(database("api"), autocommit=True) as conn:
            barrier.wait(timeout=10)
            conn.execute("SELECT activate_admin_after_pin(%s::uuid)", (candidate,))

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(activate, candidates))
    with psycopg.connect(database("admin")) as conn:
        approved = conn.execute(
            "SELECT approved_device_id FROM admin_access WHERE singleton"
        ).fetchone()[0]
        admins = conn.execute("SELECT id FROM devices WHERE is_admin").fetchall()
        assert approved in candidates
        assert admins == [(approved,)]


def test_pin_rebind_verifier_rejects_extra_execute_role(database):
    with psycopg.connect(database("migrator")) as conn:
        conn.execute(
            "GRANT EXECUTE ON FUNCTION activate_admin_after_pin(uuid) TO avelren_notifier"
        )
    with psycopg.connect(database("migrator")) as conn:
        versions = {
            row[0] for row in conn.execute("SELECT version FROM schema_migrations")
        }
        problems = schema_verify.verify_contract(conn, versions)
        assert any("PIN rebind function" in problem for problem in problems)
