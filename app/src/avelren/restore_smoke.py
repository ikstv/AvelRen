"""API smoke against a restored DB (A-07 / DR restore contract).

A restore cannot be considered proven by row counts alone. Here we bring up the
real application (FastAPI TestClient — in-process, without publishing a port)
against the DB that DATABASE_URL points to, and run a minimal but end-to-end
contract:

  1. production-guard        — we check current_database() BEFORE any mutation:
                              if 'avelren' → exit 1 immediately;
  2. GET /health            — the app actually reads observations, and
                              last_observation is not null (the restored data
                              is real);
  3. GET /active-alerts     — without headers → 401 (the auth path is in place);
  4. POST /devices          — creates a disposable installation (devices +
                              secret_hash actually work);
  5. GET /active-alerts     — with the obtained pair → 200 (a protected request,
                              constant-time secret check, a connection to
                              exactly this DB).

Run ONLY against a disposable restore_test — not against the live database. The
shell wrapper `deploy/restore-verify.sh` blocks the literal `TARGET == "avelren"`
as a first layer, but the only reliable guard is the Python current_database()
check below.
"""

import logging
import os
import sys

import psycopg
from fastapi.testclient import TestClient

from .api import app
from .config import settings
from .restore_identity import dsn_identity_problems

log = logging.getLogger("avelren.restore_smoke")


def _current_database() -> str:
    """The actual name of the database we connect to (not just a string from the URL)."""
    with psycopg.connect(settings.database_dsn, autocommit=True) as conn:
        return conn.execute("SELECT current_database()").fetchone()[0]


def main() -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # Production guard — we check the current DB BEFORE any mutation. The shell
    # wrapper blocks only the literal string "avelren", which can be bypassed via
    # URI parameters; so Python itself checks current_database(). If the answer is
    # "avelren" — immediate exit, regardless of how DATABASE_URL was constructed.
    expected_database = os.environ.get("AVELREN_RESTORE_VERIFY_TARGET")
    expected_role = os.environ.get("AVELREN_RESTORE_VERIFY_ROLE")
    if expected_database != "restore_test" or expected_role != "avelren_api":
        log.error("disposable smoke requires exact restore_test target and API role")
        return 2
    identity_problems = dsn_identity_problems(
        settings.database_dsn, expected_database, expected_role
    )
    if identity_problems:
        for problem in identity_problems:
            log.error("restore verification identity mismatch: %s", problem)
        return 1

    db_name = _current_database()
    if db_name == "avelren":
        log.error(
            "smoke refuses to run against production DB '%s' — "
            "only against a disposable restore_test", db_name
        )
        return 1

    with TestClient(app) as client:
        h = client.get("/health")
        if h.status_code != 200:
            log.error("/health not 200: %s", h.status_code)
            return 1

        # DR gap: the right schema with zero data is an unacceptable false PASS.
        # /health returns 200 even for a stale/no-data state; so we check
        # last_observation explicitly. Stale (outdated data) is acceptable for DR,
        # but null (no observations at all) means the data was not restored.
        body = h.json()
        if body.get("last_observation") is None:
            log.error(
                "/health returns last_observation=null — the restored DB contains no "
                "observations; the DR restore is considered failed"
            )
            return 1

        unauth = client.get("/active-alerts")
        if unauth.status_code != 401:
            log.error("/active-alerts without auth should have been 401, but is %s", unauth.status_code)
            return 1

        reg = client.post("/devices", json={})
        if reg.status_code != 201:
            log.error("POST /devices not 201: %s", reg.status_code)
            return 1
        creds = reg.json()

        authed = client.get(
            "/active-alerts",
            headers={
                "X-Device-Id": creds["device_id"],
                "X-Device-Secret": creds["device_secret"],
            },
        )
        if authed.status_code != 200:
            log.error("/active-alerts with auth should have been 200, but is %s", authed.status_code)
            return 1

    log.info(
        "restore smoke ok: prod-guard, health+observations, "
        "auth path, devices/secret, protected request"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
