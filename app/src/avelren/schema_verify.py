"""Перевірка, що фактична схема БД узгоджена з історією міграцій (A-07).

Використовується двічі, з одного джерела істини:
  * `migrate.py` — ПІСЛЯ застосування/перевірки міграцій. Ловить стан, де
    `schema_migrations` каже «009 застосовано», а фізично (напр. після битого
    restore) колонки чи індексу нема. Історія без фактичної схеми — брехня.
  * `deploy/restore-verify.sh` (через `python -m avelren.schema_verify`) — щоб
    restore_test доводив не counts, а реальний контракт.

Принцип A-07: історія міграцій І фактична схема мусять погоджуватися. Будь-яка
суперечність → помилка (exit 1). Ніякого fail-open, ніякого «мабуть, ок».

Контракт свідомо перелічений явно, а не виводиться з тіл міграцій: мета —
незалежна перевірка того, що ключові структури реально на місці, навіть якщо
хтось відредагував міграцію або restore втратив частину схеми.
"""

import hashlib
import logging
import sys
from pathlib import Path

import psycopg

from .config import settings

log = logging.getLogger("avelren.schema_verify")

# --- Фізичний контракт: що МУСИТЬ існувати на повністю змігрованій БД --------

REQUIRED_TABLES = [
    "checkpoints", "observations", "collector_runs", "countries",
    "devices", "subscriptions", "alerts", "subscription_state",
    "eta_targets", "eta_alerts", "health_alerts", "notification_cancels",
    "observations_hourly",  # continuous aggregate — теж relation
    "schema_migrations",
]

# Колонки, які додали пізніші міграції — саме їх втрачає частковий restore.
REQUIRED_COLUMNS = [
    ("checkpoints", "country_name"), ("checkpoints", "flag_emoji"),   # 002
    ("devices", "fcm_token"), ("devices", "platform"),               # 004
    ("devices", "is_admin"),                                         # 006
    ("devices", "secret_hash"),                                      # 007
    ("alerts", "status"), ("alerts", "send_count"),                  # 004
    ("eta_alerts", "status"),                                        # 005
    ("collector_runs", "derived_processed_at"),                      # 009
    ("collector_runs", "derived_error"),                            # 009
    ("health_alerts", "recovery_notified_at"),                       # 009
    ("health_alerts", "recovery_abandoned_at"),                      # 009
    ("notification_cancels", "kind"), ("notification_cancels", "alert_id"),
    ("notification_cancels", "device_id"), ("notification_cancels", "accepted_at"),
    ("notification_cancels", "abandoned_at"),                        # 008
]

# Часткові унікальні індекси — саме вони тримають головні інваріанти
# (один pending-алерт, один відкритий cancel тощо).
REQUIRED_INDEXES = [
    "alerts_one_pending_per_subscription",   # 004
    "eta_alerts_one_pending_per_target",     # 005
    "health_alerts_one_open_per_kind",       # 006
    "notification_cancels_open_idx",         # 008
]

REQUIRED_CONSTRAINTS = [
    "notification_cancels_kind_alert_id_key",  # 008 UNIQUE(kind, alert_id)
]

HYPERTABLES = ["observations"]
CONTINUOUS_AGGREGATES = ["observations_hourly"]


def expected_migrations(directory: Path) -> dict[str, str]:
    """version → sha256 з файлів міграцій (джерело істини для історії)."""
    out: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql")):
        body = path.read_text(encoding="utf-8")
        out[path.stem] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return out


def verify_history(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Точна відповідність історії міграцій файлам: ні пропущених, ні
    невідомих/майбутніх версій, SHA кожної збігається."""
    problems: list[str] = []
    expected = expected_migrations(directory)
    recorded = {
        row[0]: row[1]
        for row in conn.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
    }

    for version in expected.keys() - recorded.keys():
        problems.append(f"міграція {version} у файлах, але не записана як застосована")
    for version in recorded.keys() - expected.keys():
        problems.append(f"міграція {version} записана, але файлу нема (чужа/майбутня версія)")
    for version in expected.keys() & recorded.keys():
        if expected[version] != recorded[version]:
            problems.append(f"міграція {version}: SHA у БД не збігається з файлом")
    return problems


def verify_contract(conn: psycopg.Connection) -> list[str]:
    """Фізична схема: критичні таблиці/колонки/індекси/Timescale-обʼєкти."""
    problems: list[str] = []

    for table in REQUIRED_TABLES:
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"нема таблиці/relation {table}")

    for table, column in REQUIRED_COLUMNS:
        row = conn.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        ).fetchone()
        if not row:
            problems.append(f"нема колонки {table}.{column}")

    for index in REQUIRED_INDEXES:
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{index}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"нема індексу {index}")

    for constraint in REQUIRED_CONSTRAINTS:
        row = conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = %s", (constraint,)
        ).fetchone()
        if not row:
            problems.append(f"нема обмеження {constraint}")

    for ht in HYPERTABLES:
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s",
            (ht,),
        ).fetchone()
        if not row:
            problems.append(f"{ht} не є гіпертаблицею")

    for cagg in CONTINUOUS_AGGREGATES:
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = %s",
            (cagg,),
        ).fetchone()
        if not row:
            problems.append(f"нема continuous aggregate {cagg}")

    return problems


def verify(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Повна перевірка: історія + фізичний контракт. Порожньо = все узгоджено."""
    return verify_history(conn, directory) + verify_contract(conn)


def main(directory: Path) -> int:
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        problems = verify(conn, directory)
    if problems:
        log.error("схема НЕ узгоджена з історією міграцій:")
        for p in problems:
            log.error("  - %s", p)
        return 1
    log.info("схема узгоджена: %s міграцій, контракт цілий", len(expected_migrations(directory)))
    return 0


if __name__ == "__main__":
    _dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/migrations")
    sys.exit(main(_dir))
