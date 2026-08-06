"""Застосовувач міграцій.

Docker виконує файли з db/migrations лише при створенні порожньої БД, тож на
вже наповненому проді нові міграції доводилось накатувати руками — і рано чи
пізно хтось забуде, а прод розійдеться з кодом.

Тут кожна міграція застосовується рівно один раз, факт фіксується в БД, а
запуск на актуальній базі нічого не робить. Безпечно викликати щодеплою.
"""

import hashlib
import logging
import sys
from pathlib import Path

import psycopg

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


def _discover(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def _schema_exists(conn: psycopg.Connection) -> bool:
    row = conn.execute("SELECT to_regclass('public.checkpoints') IS NOT NULL").fetchone()
    return bool(row and row[0])


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

        # Разова прив'язка до вже наповненої БД: схема створена до появи цього
        # застосовувача, тож повторний прогін 001/002 нічого б не виправив, а
        # міг би впасти на вже стиснутих чанках. Фіксуємо їх як застосовані.
        if not known and _schema_exists(conn):
            log.warning("схема вже існує — позначаю наявні міграції як застосовані")
            for path in files:
                body = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
                conn.execute(
                    "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                    (path.stem, digest),
                )
                known[path.stem] = digest
            conn.commit()

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

    log.info("готово: застосовано %s, усього %s", applied, len(files))
    return 0


if __name__ == "__main__":
    sys.exit(run())
