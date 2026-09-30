"""Синтетична схема 009 з виміряними 23.09.2026 правами API та backup."""

import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from ..conftest import MIGRATIONS
from .conftest import old_schema_component_app

EVIDENCE = json.loads(
    (Path(__file__).parents[1] / "fixtures/production_009_admin_acl.json").read_text(
        encoding="utf-8-sig"
    )
)
pytestmark = pytest.mark.parametrize("database", [9], indirect=True)


@pytest.fixture
def production_009(database, conn):
    # Фікстура database створює лише одноразову БД в ізольованому CI Compose.
    # ACL відтворюємо з каталогу production, НЕ виконанням незаписаної 010.
    assert EVIDENCE["memberships"] == []
    for entry in EVIDENCE["history"]:
        file = MIGRATIONS / f"{entry['version']}.sql"
        assert hashlib.sha256(file.read_bytes()).hexdigest() == entry["sha256"]
    assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 9
    for entry in EVIDENCE["relations"]:
        assert entry["owner"] == "avelren_migrator"
    for group, kind in (("table_grants", "TABLE"), ("sequence_grants", "SEQUENCE")):
        for entry in EVIDENCE[group]:
            assert entry["privilege"] in {"SELECT", "INSERT", "UPDATE", "DELETE", "USAGE"}
            conn.execute(sql.SQL("GRANT {} ON {} public.{} TO {}").format(
                sql.SQL(entry["privilege"]), sql.SQL(kind),
                sql.Identifier(entry["relname"]), sql.Identifier(entry["rolname"]),
            ))
    for entry in EVIDENCE["column_grants"]:
        assert entry["privilege"] in {"SELECT", "INSERT", "UPDATE"}
        conn.execute(sql.SQL("GRANT {} ({}) ON public.{} TO {}").format(
            sql.SQL(entry["privilege"]), sql.Identifier(entry["attname"]),
            sql.Identifier(entry["relname"]), sql.Identifier(entry["rolname"]),
        ))
    # bootstrap вже встановив ці schema ACL; звіряємо позитивні й негативні.
    for role in ("avelren_api", "avelren_backup", "avelren_migrator"):
        for privilege in ("USAGE", "CREATE"):
            expected = {"rolname": role, "privilege": privilege} in EVIDENCE["schema_grants"]
            assert conn.execute(
                "SELECT has_schema_privilege(%s,'public',%s) AS allowed", (role, privilege)
            ).fetchone()["allowed"] == expected
    return database


@pytest.fixture
def legacy_dsn(production_009):
    # Нове тестове ім'я, ті самі атрибути фактичного production API login.
    name = f"avelren_legacy_{uuid.uuid4().hex}"
    role = next(r for r in EVIDENCE["roles"] if r["rolname"] == "avelren")
    assert all(role[k] for k in (
        "rolsuper", "rolinherit", "rolcreaterole", "rolcreatedb", "rolbypassrls"
    ))
    with psycopg.connect(production_009("admin"), autocommit=True) as connection:
        connection.execute(sql.SQL(
            "CREATE ROLE {} LOGIN SUPERUSER INHERIT CREATEROLE CREATEDB BYPASSRLS "
            "PASSWORD 'ci-only'"
        ).format(sql.Identifier(name)))
        try:
            yield make_conninfo(production_009("admin"), user=name)
        finally:
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@pytest.fixture
def client_for(monkeypatch):
    from avelren import db, ratelimit
    from avelren.api import app
    from avelren.config import settings

    @contextmanager
    def open_client(dsn, *, component_only=False):
        with monkeypatch.context() as patch:
            patch.setattr(settings, "database_url", dsn)
            patch.setattr(db, "_pool", None)
            ratelimit._hits.clear()
            try:
                test_app = old_schema_component_app() if component_only else app
                with TestClient(test_app) as client:
                    yield client
                assert db._pool.closed
            finally:
                db._pool = None
                ratelimit._hits.clear()

    return open_client


def history(conn):
    return conn.execute(
        "SELECT version,sha256,applied_at FROM schema_migrations ORDER BY version"
    ).fetchall()


@pytest.mark.parametrize("identity", ["legacy", "api"])
def test_009_health_and_existing_admin_handlers(
    production_009, legacy_dsn, client_for, identity, device, conn, checkpoint,
):
    before = history(conn)
    conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (device.device_id,))
    conn.execute("INSERT INTO observations VALUES (now(), %s, 3600, 80, false)", (checkpoint,))
    dsn = legacy_dsn if identity == "legacy" else production_009("api")
    # The installed new service refuses schema 009 at startup. These route
    # assertions cover the handlers against historical ACLs, not old runtime.
    with client_for(dsn, component_only=True) as client:
        assert client.get("/health").status_code == 200
        telemetry = client.get("/admin/telemetry", headers=device.headers())
        assert telemetry.status_code == 200, telemetry.text
        status = client.get("/admin/access", headers=device.headers())
        assert status.status_code == 200 and status.json()["state"] == "unavailable"
        response = client.post("/admin/access", headers=device.headers(), json={"pin": "7392"})
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "unavailable"
    assert history(conn) == before
    assert conn.execute(
        "SELECT vehicles_in_queue FROM observations WHERE checkpoint_id=%s", (checkpoint,)
    ).fetchone()["vehicles_in_queue"] == 80
    assert conn.execute("SELECT to_regclass('public.admin_access') AS t").fetchone()["t"] is None
    admin = conn.execute("SELECT is_admin FROM devices WHERE id=%s", (device.device_id,))
    assert admin.fetchone()["is_admin"]


def test_009_upgrade_approval_pin_and_backup(
    production_009, client_for, device, installation, conn, monkeypatch,
):
    from avelren import admin_approve, migrate, schema_verify
    from avelren.config import settings

    old = installation()
    conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (old.device_id,))
    before = history(conn)
    assert migrate.run(MIGRATIONS) == 0  # settings досі вказує на test migrator.
    after = history(conn)
    assert len(after) == 15 and after[:9] == before
    with psycopg.connect(production_009("migrator")) as verifier:
        assert schema_verify.verify(verifier, MIGRATIONS) == []
    assert migrate.run(MIGRATIONS) == 0
    assert history(conn) == after


    # Міграція не обирає пристрій і не відкликає чинний канал сповіщень.
    assert conn.execute("SELECT approved_device_id,pin_hash FROM admin_access").fetchone() == {
        "approved_device_id": None, "pin_hash": None,
    }
    with client_for(production_009("api")) as client:
        status = client.get("/admin/access", headers=device.headers())
        assert status.status_code == 200 and status.json()["state"] == "unavailable"
        assert client.get("/admin/telemetry", headers=old.headers()).status_code == 200
    # Виконуємо справжню host-side команду з синтетичним PIN у тестовій БД.
    with monkeypatch.context() as patch:
        patch.setattr(settings, "database_url", production_009("migrator"))
        patch.setattr("sys.argv", ["admin_approve", device.device_id, "--set-pin"])
        patch.setattr("getpass.getpass", lambda _: "7392")
        admin_approve.main()
    with client_for(production_009("api")) as client:
        assert client.get("/admin/access", headers=device.headers()).json()["state"] == "ready"
        wrong = client.post("/admin/access", headers=device.headers(), json={"pin": "0000"})
        assert wrong.json()["state"] == "invalid_pin"
        assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 1
        assert client.get("/admin/telemetry", headers=device.headers()).status_code == 403
        correct = client.post("/admin/access", headers=device.headers(), json={"pin": "7392"})
        assert correct.status_code == 200, correct.text
        assert correct.json()["state"] == "authorized"
        assert client.get("/admin/telemetry", headers=device.headers()).status_code == 200
        assert client.get("/admin/telemetry", headers=old.headers()).status_code == 403
    admins = [str(r["id"]) for r in conn.execute("SELECT id FROM devices WHERE is_admin")]
    assert admins == [device.device_id]
    with psycopg.connect(production_009("backup"), autocommit=True) as backup:
        assert backup.execute("SELECT count(*) FROM admin_access").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            backup.execute("UPDATE admin_access SET failures=0")
    with psycopg.connect(production_009("api"), autocommit=True) as api:
        for statement in (
            "UPDATE admin_access SET approved_device_id=NULL",
            "UPDATE admin_access SET pin_hash=NULL",
            "UPDATE devices SET is_admin=false WHERE false",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                api.execute(statement)
    assert history(conn) == after


def test_previous_api_database_contract_survives_014(
    production_009, device, installation, conn, monkeypatch,
):
    """The API shipped immediately before this PR can roll back onto schema 014.

    Keep the database operations below aligned with the previous
    ``admin_access_api.access`` at base commit 523eb92. This is deliberately a
    frozen compatibility harness rather than the current FastAPI route: using
    the current route would silently stop testing the documented rollback.
    """
    from avelren import admin_approve, migrate
    from avelren.admin_pin import verify_pin
    from avelren.config import settings

    assert migrate.run(MIGRATIONS) == 0
    assert len(history(conn)) == 15

    # The previous API only admits the already-approved installation.
    with monkeypatch.context() as patch:
        patch.setattr(settings, "database_url", production_009("migrator"))
        patch.setattr("sys.argv", ["admin_approve", device.device_id, "--set-pin"])
        patch.setattr("getpass.getpass", lambda _: "7392")
        admin_approve.main()

    with psycopg.connect(production_009("api"), row_factory=dict_row) as previous_api:
        installed = previous_api.execute(
            "SELECT 1 FROM schema_migrations "
            "WHERE version='013_admin_installation_lock'"
        ).fetchone()
        assert installed is not None
        access = previous_api.execute(
            "SELECT approved_device_id,pin_hash,failures,locked_until "
            "FROM admin_access WHERE singleton FOR UPDATE"
        ).fetchone()
        candidate = previous_api.execute(
            "SELECT admin_blocked_until FROM devices WHERE id=%s FOR UPDATE",
            (device.device_id,),
        ).fetchone()
        assert candidate["admin_blocked_until"] is None
        assert str(access["approved_device_id"]) == device.device_id
        assert verify_pin("7392", access["pin_hash"])
        previous_api.execute(
            "UPDATE admin_access SET failures=0,locked_until=NULL WHERE singleton"
        )
        previous_api.execute(
            "SELECT activate_approved_admin(%s::uuid)", (device.device_id,),
        )

    assert conn.execute(
        "SELECT is_admin FROM devices WHERE id=%s", (device.device_id,),
    ).fetchone()["is_admin"] is True

    # Its foreign-installation branch must also retain the exact UPDATE grant
    # used to fail closed for 24 hours; migration 014 must not revoke it.
    foreign = installation()
    with psycopg.connect(production_009("api"), row_factory=dict_row) as previous_api:
        blocked = previous_api.execute(
            "UPDATE devices "
            "SET admin_blocked_until=clock_timestamp()+interval '24 hours' "
            "WHERE id=%s RETURNING admin_blocked_until",
            (foreign.device_id,),
        ).fetchone()
        assert blocked["admin_blocked_until"] is not None
