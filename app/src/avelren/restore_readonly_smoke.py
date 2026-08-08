"""Read-only application smoke used only by the production restore orchestrator."""

import logging
import os
import sys

import psycopg
from fastapi.testclient import TestClient

from .api import app
from .config import settings

log = logging.getLogger("avelren.restore_readonly_smoke")

PRODUCTION_VERIFY_CONTEXT = "AVELREN-INTERNAL-PRODUCTION-VERIFY"


def _database_facts() -> tuple[str, int, int]:
    with psycopg.connect(settings.database_dsn, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT current_database(),
                   (SELECT count(*) FROM schema_migrations),
                   (SELECT count(*) FROM timescaledb_information.hypertables)
            """
        ).fetchone()
    return str(row[0]), int(row[1]), int(row[2])


def main() -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    expected = os.environ.get("AVELREN_RESTORE_VERIFY_TARGET")
    context = os.environ.get("AVELREN_PRODUCTION_VERIFY_CONTEXT")
    if expected != "avelren" or context != PRODUCTION_VERIFY_CONTEXT:
        log.error("production read-only smoke requires exact internal context and target")
        return 2

    database, migrations, hypertables = _database_facts()
    if database != expected or migrations < 1 or hypertables < 1:
        log.error(
            "restored database facts invalid: database=%s migrations=%s hypertables=%s",
            database,
            migrations,
            hypertables,
        )
        return 1

    # GET-only application calls. Unlike restore_smoke, this module never
    # registers a device or changes restored production data.
    with TestClient(app) as client:
        health = client.get("/health")
        checkpoints = client.get("/checkpoints", params={"include_stale": True})
    if health.status_code != 200 or checkpoints.status_code != 200:
        log.error(
            "read-only application smoke failed: health=%s checkpoints=%s",
            health.status_code,
            checkpoints.status_code,
        )
        return 1
    if health.json().get("last_observation") is None:
        log.error("restored production database has no observations")
        return 1

    log.info(
        "production read-only smoke ok: migrations=%s hypertables=%s checkpoints=%s",
        migrations,
        hypertables,
        len(checkpoints.json()),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
