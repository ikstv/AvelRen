"""API-smoke проти відновленої БД (A-07 / DR restore contract).

Restore не можна вважати доведеним лише за counts рядків. Тут ми піднімаємо
справжній застосунок (FastAPI TestClient — у процесі, без публікації порту)
проти БД, на яку вказує DATABASE_URL, і прогонимо мінімальний, але наскрізний
контракт:

  1. production-guard        — перевіряємо current_database() ДО будь-якої
                              mutation: якщо 'avelren' → exit 1 негайно;
  2. GET /health            — застосунок реально читає observations, і
                              last_observation не null (відновлені дані реальні);
  3. GET /active-alerts     — без заголовків → 401 (auth-контур на місці);
  4. POST /devices          — створює disposable installation (devices +
                              secret_hash реально працюють);
  5. GET /active-alerts     — з отриманою парою → 200 (protected-запит,
                              звірка secret constant-time, зʼєднання саме з
                              цією БД).

Запускати ЛИШЕ проти disposable restore_test — не проти бойової бази. Shell-wrapper
`deploy/restore-verify.sh` блокує literal `TARGET == "avelren"` як перший шар, але
єдиним надійним guard-ом є Python-перевірка current_database() нижче.
"""

import logging
import sys

import psycopg
from fastapi.testclient import TestClient

from .api import app
from .config import settings

log = logging.getLogger("avelren.restore_smoke")


def _current_database() -> str:
    """Фактична назва бази, до якої підключаємося (не просто рядок з URL)."""
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        return conn.execute("SELECT current_database()").fetchone()[0]


def main() -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # Production guard — перевіряємо поточну БД ДО будь-якої mutation.
    # Shell-wrapper блокує лише literal рядок "avelren", що обходиться параметрами
    # URI; тому Python сам звіряє current_database(). Якщо відповідь "avelren" —
    # негайний вихід, незалежно від того, як саме сформований DATABASE_URL.
    db_name = _current_database()
    if db_name == "avelren":
        log.error(
            "smoke відмовляється запускатися проти production БД '%s' — "
            "лише проти disposable restore_test", db_name
        )
        return 1

    with TestClient(app) as client:
        h = client.get("/health")
        if h.status_code != 200:
            log.error("/health не 200: %s", h.status_code)
            return 1

        # DR gap: права схема з нульовими даними — неприйнятний false PASS.
        # /health повертає 200 навіть для stale/no-data стану; тому перевіряємо
        # last_observation явно. Stale (застарілі дані) прийнятно для DR,
        # але null (взагалі нема спостережень) означає, що дані не відновились.
        body = h.json()
        if body.get("last_observation") is None:
            log.error(
                "/health повертає last_observation=null — відновлена БД не містить "
                "спостережень; DR restore вважається невдалим"
            )
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

    log.info(
        "restore smoke ok: prod-guard, health+observations, "
        "auth-контур, devices/secret, protected-запит"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
