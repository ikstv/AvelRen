"""API-smoke проти відновленої БД (A-07 / DR restore contract).

Restore не можна вважати доведеним лише за counts рядків. Тут ми піднімаємо
справжній застосунок (FastAPI TestClient — у процесі, без публікації порту)
проти БД, на яку вказує DATABASE_URL, і прогонимо мінімальний, але наскрізний
контракт:

  1. GET /health            — застосунок реально читає observations;
  2. GET /active-alerts     — без заголовків → 401 (auth-контур на місці);
  3. POST /devices          — створює disposable installation (devices +
                              secret_hash реально працюють);
  4. GET /active-alerts     — з отриманою парою → 200 (protected-запит,
                              звірка secret constant-time, зʼєднання саме з
                              цією БД).

Запускати ЛИШЕ проти disposable restore_test — не проти бойової бази. Гарантує
це `deploy/restore-verify.sh` (відмовляється працювати з `avelren`), а сам
smoke створює в БД тестовий рядок devices, тож на проді його гнати не можна.
"""

import logging
import sys

from fastapi.testclient import TestClient

from .api import app
from .config import settings

log = logging.getLogger("avelren.restore_smoke")


def main() -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    with TestClient(app) as client:
        h = client.get("/health")
        if h.status_code != 200:
            log.error("/health не 200: %s", h.status_code)
            return 1

        unauth = client.get("/active-alerts")
        if unauth.status_code != 401:
            log.error("/active-alerts без auth мав бути 401, а є %s", unauth.status_code)
            return 1

        reg = client.post("/devices", json={})
        if reg.status_code != 201:
            log.error("POST /devices не 201: %s", reg.status_code)
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
            log.error("/active-alerts з auth мав бути 200, а є %s", authed.status_code)
            return 1

    log.info("restore smoke ok: health, auth-контур, devices/secret, protected-запит")
    return 0


if __name__ == "__main__":
    sys.exit(main())
