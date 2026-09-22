"""Реальні обмеження ролей на тимчасовій TimescaleDB."""

import psycopg
import pytest
from psycopg import sql

from .conftest import ROLES


def test_roles_and_owners(database):
    with psycopg.connect(database("admin")) as conn:
        rows = conn.execute(
            """
            SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
            FROM pg_roles WHERE rolname = ANY(%s)
        """,
            ([f"avelren_{r}" for r in ROLES],),
        ).fetchall()
        assert len(rows) == len(ROLES)
        assert all(row[1:] == (False, False, False, False) for row in rows)
        assert (
            conn.execute("""
            SELECT count(*) FROM pg_auth_members m
            JOIN pg_roles r ON r.oid=m.member
            WHERE r.rolname LIKE 'avelren_%%'
        """).fetchone()[0]
            == 0
        )
        owners = conn.execute("""
            SELECT DISTINCT pg_get_userbyid(c.relowner)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
        """).fetchall()
        assert owners == [("avelren_migrator",)]


def test_backup_reads_every_public_table_and_sequence_but_cannot_write(database):
    with psycopg.connect(database("admin")) as conn:
        relations = conn.execute("""
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
        """).fetchall()
    assert relations
    with psycopg.connect(database("backup"), autocommit=True) as conn:
        for (name,) in relations:
            conn.execute(sql.SQL("SELECT * FROM public.{} LIMIT 0").format(sql.Identifier(name)))
        for statement in [
            "DELETE FROM devices WHERE false",
            "UPDATE observations SET wait_time_seconds=0 WHERE false",
            "CREATE TABLE public.unauthorized(id int)",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


@pytest.mark.parametrize("role", ["collector", "notifier", "watchdog", "api"])
def test_runtime_cannot_modify_schema_or_read_device_secrets(database, role):
    with psycopg.connect(database(role), autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 11
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("CREATE TABLE public.unauthorized(id int)")
        if role != "api":
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT secret_hash FROM devices LIMIT 0")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE devices SET is_admin=true WHERE false")
