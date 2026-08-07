"""Застосовувач міграцій.

Docker виконує файли з db/migrations лише при створенні порожньої БД, тож на
вже наповненому проді нові міграції доводилось накатувати руками — і рано чи
пізно хтось забуде, а прод розійдеться з кодом.

Тут кожна міграція застосовується рівно один раз, факт фіксується в БД, а
запуск на актуальній базі нічого не робить. Безпечно викликати щодеплою.

**A-07 — fail-closed.** Раніше при порожньому `schema_migrations`, але наявній
таблиці `checkpoints`, застосовувач позначав УСІ файли застосованими на
евристику по одній таблиці. Після битого/старого restore це створювало дуже
переконливу брехню: історія каже «001..NNN застосовано», а структур насправді
нема. Тепер:

  * чиста БД (жодного відомого AvelRen-обʼєкта) → створюємо історію й
    застосовуємо все;
  * коректна історія → звичайний шлях (SHA-перевірка + застосування нових);
  * будь-який AvelRen-обʼєкт існує, а довіреної історії нема → **FAIL CLOSED**.

Автоматичного baseline більше немає. Якщо колись треба узаконити legacy-БД без
історії — це свідома ручна процедура оператора (перевірити структуру, вставити
рядки в schema_migrations), а не щось, що відбувається саме собою на deploy.

Після застосування схема звіряється з історією (`schema_verify`): якщо
`schema_migrations` каже одне, а фізична схема інше (напр. restore втратив
колонку) — теж exit 1.
"""

import hashlib
import logging
import sys
from pathlib import Path

import psycopg

from . import schema_verify
from .config import settings

log = logging.getLogger("avelren.migrate")

MIGRATIONS_DIR = Path("/migrations")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text        PRIMARY KEY,
    sha256      text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""

# Повний набір відомих AvelRen-обʼєктів. Наявність БУДЬ-ЯКОГО з них при
# порожній історії — ознака legacy/часткового стану, а не чистої БД. Дивитися
# лише на `checkpoints` мало: битий restore міг мати `devices`/`alerts` без
# `checkpoints`.
KNOWN_OBJECTS = [
    "checkpoints", "observations", "collector_runs", "countries",
    "devices", "subscriptions", "alerts", "subscription_state",
    "eta_targets", "eta_alerts", "health_alerts", "notification_cancels",
    "observations_hourly",
]


def _discover(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def _existing_objects(conn: psycopg.Connection) -> list[str]:
    found = []
    for name in KNOWN_OBJECTS:
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{name}",)).fetchone()
        if row and row[0] is not None:
            found.append(name)
    return found


def run(directory: Path = MIGRATIONS_DIR) -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    files = _discover(directory)
    if not files:
        log.warning("міграцій не знайдено в %s", directory)
        return 0

    applied = 0
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        conn.execute(_SCHEMA)
        conn.commit()

        known = {
            row[0]: row[1]
            for row in conn.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
        }

        # A-07 fail-closed: історія порожня — вирішуємо за фактичним станом
        # схеми, а не за однією таблицею.
        if not known:
            existing = _existing_objects(conn)
            if existing:
                log.error(
                    "У БД існує схема AvelRen (%s), але довіреної історії міграцій нема. "
                    "Автоматичний baseline заборонено (A-07): невідомий/частковий стан "
                    "не можна оголошувати застосованим. Якщо це відома legacy-БД — "
                    "узаконьте baseline вручну за runbook, звіривши структуру.",
                    ", ".join(existing),
                )
                return 1
            log.info("чиста БД — застосовую всі міграції з нуля")

        for path in files:
            version = path.stem
            body = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

            if version in known:
                if known[version] != digest:
                    # Мовчазна розбіжність гірша за падіння: означає, що вже
                    # застосований файл змінили, і БД більше не відповідає коду.
                    log.error(
                        "міграцію %s змінено після застосування — виправте вручну", version
                    )
                    return 1
                continue

            log.info("застосовую %s", version)
            try:
                conn.execute(body)
                conn.execute(
                    "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                    (version, digest),
                )
                conn.commit()
                applied += 1
            except Exception as exc:
                conn.rollback()
                log.error("міграція %s не вдалася: %s", version, exc)
                return 1

        # Історія тепер повна — але чи погоджується з нею фізична схема?
        # Битий restore міг мати правильні SHA й водночас втратити колонку.
        problems = schema_verify.verify(conn, directory)
        if problems:
            log.error("схема суперечить історії міграцій (A-07):")
            for p in problems:
                log.error("  - %s", p)
            return 1

    log.info("готово: застосовано %s, усього %s", applied, len(files))
    return 0


if __name__ == "__main__":
    # Необовʼязковий аргумент — шлях до міграцій: у контейнері це /migrations,
    # а CI запускає з кореня репозиторію.
    sys.exit(run(Path(sys.argv[1]) if len(sys.argv) > 1 else MIGRATIONS_DIR))
