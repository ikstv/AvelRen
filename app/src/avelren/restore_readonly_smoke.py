"""GET-only API smoke used only by the production restore orchestrator."""

import logging
import os
import sys

from fastapi.testclient import TestClient

from .api import app
from .config import settings
from .restore_identity import dsn_identity_problems

log = logging.getLogger("avelren.restore_readonly_smoke")

PRODUCTION_VERIFY_CONTEXT = "AVELREN-INTERNAL-PRODUCTION-VERIFY"


def main() -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    expected = os.environ.get("AVELREN_RESTORE_VERIFY_TARGET")
    expected_role = os.environ.get("AVELREN_RESTORE_VERIFY_ROLE")
    context = os.environ.get("AVELREN_PRODUCTION_VERIFY_CONTEXT")
    if (
        expected != "avelren"
        or expected_role != "avelren_api"
        or context != PRODUCTION_VERIFY_CONTEXT
    ):
        log.error("production read-only smoke requires exact context, target, and role")
        return 2

    identity_problems = dsn_identity_problems(settings.database_dsn, expected, expected_role)
    if identity_problems:
        for problem in identity_problems:
            log.error("restore verification identity mismatch: %s", problem)
        return 1

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

    log.info("production read-only API smoke ok: checkpoints=%s", len(checkpoints.json()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
