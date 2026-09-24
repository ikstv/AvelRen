"""Історія міграцій має відповідати файлам і фізичній схемі."""

import hashlib
import shutil

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
        assert len(after) == 12
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
