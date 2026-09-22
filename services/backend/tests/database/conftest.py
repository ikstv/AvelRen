"""Тимчасові копії тестової БД; робочі DSN не приймаються."""

import os
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

BASE = "avelren_database_test"
ROLES = ("migrator", "backup", "collector", "notifier", "watchdog", "api")
MIGRATIONS = Path(__file__).resolve().parents[4] / "db/migrations"


def dsn(role, database):
    if role not in (*ROLES, "admin") or not database.startswith("avelren_"):
        raise ValueError("Unexpected test identity")
    return f"postgresql://avelren_{role}:ci-only@test-db:5432/{database}"


def pytest_configure(config):
    expected = conninfo_to_dict(dsn("migrator", BASE))
    actual = conninfo_to_dict(os.environ.get("DATABASE_URL", ""))
    if os.environ.get("AVELREN_DATABASE_TEST") != "1" or actual != expected:
        raise pytest.UsageError("Database tests require the isolated test_database.sh runner")


@pytest.fixture(autouse=True)
def no_http(monkeypatch):
    def denied(*args, **kwargs):
        raise RuntimeError("HTTP заборонено в тестах БД")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)


@pytest.fixture
def database(monkeypatch, request, tmp_path):
    from avelren import migrate
    from avelren.config import settings

    name = f"avelren_case_{uuid.uuid4().hex}_test"
    maintenance = "postgresql://avelren_admin:ci-only@test-db:5432/postgres"
    with psycopg.connect(maintenance, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE DATABASE {} OWNER avelren_admin").format(sql.Identifier(name))
        )
        try:
            admin.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
            )
            admin.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(name),
                    sql.SQL(", ").join(sql.Identifier(f"avelren_{r}") for r in ROLES),
                )
            )
            with psycopg.connect(dsn("admin", name), autocommit=True) as target:
                target.execute("CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public")
                target.execute("ALTER SCHEMA public OWNER TO avelren_admin")
                target.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
                target.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.SQL(", ").join(sql.Identifier(f"avelren_{r}") for r in ROLES)
                    )
                )
                target.execute("GRANT CREATE ON SCHEMA public TO avelren_migrator")
            monkeypatch.setattr(settings, "database_url", dsn("migrator", name))
            migration_directory = MIGRATIONS
            if getattr(request, "param", 11) == 9:
                migration_directory = tmp_path / "prefix"
                migration_directory.mkdir()
                for file in sorted(MIGRATIONS.glob("*.sql"))[:9]:
                    (migration_directory / file.name).write_bytes(file.read_bytes())
            assert migrate.run(migration_directory) == 0
            yield lambda role: dsn(role, name)
        finally:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
