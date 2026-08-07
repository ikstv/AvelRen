"""Перевірка, що фактична схема БД узгоджена з історією міграцій (A-07).

Використовується двічі, з одного джерела істини:
  * `migrate.py` — ДО застосування нових міграцій (prefix-aware verify_contract),
    щоб виявити битий restore ДО того, як нові файли будуть застосовані; і ПІСЛЯ
    (повний verify), щоб зловити будь-яку розбіжність схеми з повною історією.
  * `deploy/restore-verify.sh` (через `python -m avelren.schema_verify`) — щоб
    restore_test доводив не counts, а реальний контракт.

Принцип A-07: історія міграцій І фактична схема мусять погоджуватися. Будь-яка
суперечність → помилка (exit 1). Ніякого fail-open, ніякого «мабуть, ок».

Контракт свідомо перелічений явно, а не виводиться з тіл міграцій: мета —
незалежна перевірка того, що ключові структури реально на місці, навіть якщо
хтось відредагував міграцію або restore втратив частину схеми.

Кожен запис анотований версією міграції, яка його створює. verify_contract()
приймає recorded_versions; якщо None — перевіряє все (post-apply). Якщо множина
— перевіряє лише об'єкти, введені тими версіями (pre-apply prefix gate).
"""

import hashlib
import logging
import sys
from pathlib import Path

import psycopg

from .config import settings

log = logging.getLogger("avelren.schema_verify")

# --- Version-annotated physical contract ------------------------------------
# Формат: (since_version | None, ...деталі об'єкта)
# since=None → always required (schema_migrations).
# Prefix gate в migrate.py фільтрує за recorded_versions.

_TABLES_V: list[tuple[str | None, str]] = [
    ("001_init", "checkpoints"),
    ("001_init", "observations"),
    ("001_init", "collector_runs"),
    ("002_countries", "countries"),
    ("004_alerts", "devices"),
    ("004_alerts", "subscriptions"),
    ("004_alerts", "alerts"),
    ("004_alerts", "subscription_state"),
    ("005_eta_targets", "eta_targets"),
    ("005_eta_targets", "eta_alerts"),
    ("006_admin_devices", "health_alerts"),
    ("008_notification_cancels", "notification_cancels"),
    ("001_init", "observations_hourly"),   # continuous aggregate, 001_init
    (None, "schema_migrations"),
]

_COLUMNS_V: list[tuple[str | None, str, str]] = [
    ("002_countries", "checkpoints", "country_name"),
    ("002_countries", "checkpoints", "flag_emoji"),
    ("004_alerts", "devices", "fcm_token"),
    ("004_alerts", "devices", "platform"),
    ("006_admin_devices", "devices", "is_admin"),
    ("007_device_secret", "devices", "secret_hash"),
    ("004_alerts", "alerts", "status"),
    ("004_alerts", "alerts", "send_count"),
    ("005_eta_targets", "eta_alerts", "status"),
    ("009_observability", "collector_runs", "derived_processed_at"),
    ("009_observability", "collector_runs", "derived_error"),
    ("009_observability", "health_alerts", "recovery_notified_at"),
    ("009_observability", "health_alerts", "recovery_abandoned_at"),
    ("008_notification_cancels", "notification_cancels", "kind"),
    ("008_notification_cancels", "notification_cancels", "alert_id"),
    ("008_notification_cancels", "notification_cancels", "device_id"),
    ("008_notification_cancels", "notification_cancels", "accepted_at"),
    ("008_notification_cancels", "notification_cancels", "abandoned_at"),
]

# Інваріант-захисні індекси: перевіряємо exact semantic definition —
# table + columns + partial predicate. Той самий name з іншими columns або
# іншим WHERE — вже не той інваріант (напр. "один pending" перестає гарантуватись).
# (version, index_name, table, columns, predicate_expr_normalized)
_UNIQUE_PARTIAL_INDEXES_V: list[tuple[str, str, str, tuple[str, ...], str]] = [
    ("004_alerts", "alerts_one_pending_per_subscription", "alerts",
     ("subscription_id",), "(status = 'pending'::text)"),
    ("005_eta_targets", "eta_alerts_one_pending_per_target", "eta_alerts",
     ("target_id",), "(status = 'pending'::text)"),
    ("006_admin_devices", "health_alerts_one_open_per_kind", "health_alerts",
     ("kind",), "(resolved_at IS NULL)"),
]

# Звичайні (не-unique) індекси: лише перевірка існування.
_INDEXES_V: list[tuple[str, str]] = [
    ("008_notification_cancels", "notification_cancels_open_idx"),
]

# Іменовані UNIQUE-обмеження. ON CONFLICT у API прямо покладається на них;
# якщо constraint загубився при restore або має інші columns — POST впаде.
# (version, constraint_name, table, columns)
_CONSTRAINTS_V: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("004_alerts", "subscriptions_device_id_checkpoint_id_threshold_key",
     "subscriptions", ("device_id", "checkpoint_id", "threshold")),
    ("008_notification_cancels", "notification_cancels_kind_alert_id_key",
     "notification_cancels", ("kind", "alert_id")),
]

_HYPERTABLES_V: list[tuple[str, str]] = [
    ("001_init", "observations"),
]

_CONTINUOUS_AGGREGATES_V: list[tuple[str, str]] = [
    ("001_init", "observations_hourly"),
]


def _want(since: str | None, recorded: set[str] | None) -> bool:
    """Чи треба перевіряти цей об'єкт при заданому наборі recorded versions."""
    if recorded is None:
        return True
    if since is None:
        return True
    return since in recorded


# ---------------------------------------------------------------------------


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


def verify_contract(
    conn: psycopg.Connection,
    recorded_versions: set[str] | None = None,
) -> list[str]:
    """Фізична схема: таблиці/колонки/індекси/constraints/Timescale-об'єкти.

    recorded_versions=None → повна перевірка (post-apply, всі об'єкти).
    recorded_versions=set  → лише об'єкти, введені тими версіями (pre-apply
    prefix gate: виявити битий restore ДО застосування нових файлів).
    """
    problems: list[str] = []
    def want(since: str | None) -> bool:
        return _want(since, recorded_versions)

    for since, table in _TABLES_V:
        if not want(since):
            continue
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"нема таблиці/relation {table}")

    for since, table, column in _COLUMNS_V:
        if not want(since):
            continue
        row = conn.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        ).fetchone()
        if not row:
            problems.append(f"нема колонки {table}.{column}")

    # Інваріант-індекси: exact semantic definition — same name недостатньо.
    # Хтось міг DROP+CREATE із тим же іменем, але іншими columns/predicate;
    # інваріант зникає, а тільки uniqueness+partial це не ловить.
    for since, index, want_table, want_cols, want_pred in _UNIQUE_PARTIAL_INDEXES_V:
        if not want(since):
            continue
        row = conn.execute(
            """
            SELECT
                t.relname AS table_name,
                i.indisunique,
                i.indpred IS NOT NULL AS is_partial,
                pg_get_expr(i.indpred, i.indrelid) AS predicate,
                (
                    SELECT array_agg(a.attname ORDER BY x.ord)
                    FROM unnest(i.indkey::int[]) WITH ORDINALITY AS x(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid AND a.attnum = x.attnum
                ) AS columns
            FROM pg_class c
            JOIN pg_index i ON i.indexrelid = c.oid
            JOIN pg_class t ON t.oid = i.indrelid
            WHERE c.relname = %s AND c.relkind = 'i'
            """,
            (index,),
        ).fetchone()
        if not row:
            problems.append(f"нема індексу {index}")
            continue
        table_name, is_unique, is_partial, predicate, columns = row
        if table_name != want_table:
            problems.append(
                f"індекс {index} на таблиці {table_name}, очікували {want_table}"
            )
        if not is_unique:
            problems.append(f"індекс {index} не є UNIQUE (інваріант порушено)")
        if not is_partial:
            problems.append(f"індекс {index} не є partial — нема WHERE-умови")
        actual_cols = tuple(columns or ())
        if actual_cols != want_cols:
            problems.append(
                f"індекс {index}: columns {actual_cols}, очікували {want_cols}"
            )
        if is_partial and predicate != want_pred:
            problems.append(
                f"індекс {index}: predicate {predicate!r}, очікували {want_pred!r}"
            )

    for since, index in _INDEXES_V:
        if not want(since):
            continue
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{index}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"нема індексу {index}")

    # UNIQUE-constraints: exact table + contype='u' + columns. Тільки name
    # недостатньо: rename+recreate з іншими columns дає той же conname, але
    # ON CONFLICT (want_cols) впаде на проді.
    for since, constraint, want_table, want_cols in _CONSTRAINTS_V:
        if not want(since):
            continue
        row = conn.execute(
            """
            SELECT
                c.contype,
                t.relname AS table_name,
                (
                    SELECT array_agg(a.attname ORDER BY x.ord)
                    FROM unnest(c.conkey::int[]) WITH ORDINALITY AS x(attnum, ord)
                    JOIN pg_attribute a
                      ON a.attrelid = c.conrelid AND a.attnum = x.attnum
                ) AS columns
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE c.conname = %s
            """,
            (constraint,),
        ).fetchone()
        if not row:
            problems.append(f"нема обмеження {constraint}")
            continue
        contype, table_name, columns = row
        if contype != "u":
            problems.append(
                f"обмеження {constraint}: contype={contype!r}, очікували 'u' (UNIQUE)"
            )
        if table_name != want_table:
            problems.append(
                f"обмеження {constraint} на таблиці {table_name}, очікували {want_table}"
            )
        actual_cols = tuple(columns or ())
        if actual_cols != want_cols:
            problems.append(
                f"обмеження {constraint}: columns {actual_cols}, очікували {want_cols}"
            )

    for since, ht in _HYPERTABLES_V:
        if not want(since):
            continue
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s",
            (ht,),
        ).fetchone()
        if not row:
            problems.append(f"{ht} не є гіпертаблицею")

    for since, cagg in _CONTINUOUS_AGGREGATES_V:
        if not want(since):
            continue
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = %s",
            (cagg,),
        ).fetchone()
        if not row:
            problems.append(f"нема continuous aggregate {cagg}")

    return problems


def verify(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Повна перевірка: історія + фізичний контракт для фактично записаних версій.

    Контракт фільтрується за recorded versions, а не жорстко по всіх _V записах:
    коли `directory` містить lише prefix (партіальний набір міграцій, напр. у
    тестах), verify не повинен вимагати об'єкти майбутніх міграцій. Розбіжність
    між файлами й записаним ловить verify_history."""
    history_problems = verify_history(conn, directory)
    recorded = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    return history_problems + verify_contract(conn, recorded_versions=recorded)


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
