"""Verification that the actual DB schema agrees with the migration history (A-07).

Used twice, from a single source of truth:
  * `migrate.py` — BEFORE applying new migrations (prefix-aware verify_contract),
    to detect a corrupt restore BEFORE the new files are applied; and AFTER
    (full verify), to catch any schema divergence from the full history.
  * `deploy/restore-verify.sh` (via `python -m avelren.schema_verify`) — so
    restore_test proves not counts but the real contract.

A-07 principle: the migration history AND the actual schema must agree. Any
contradiction → an error (exit 1). No fail-open, no "probably ok".

The contract is deliberately listed explicitly rather than derived from the
migration bodies: the goal is an independent check that the key structures are
really in place, even if someone edited a migration or the restore lost part of
the schema.

Each entry is annotated with the migration version that creates it.
verify_contract() takes recorded_versions; if None — it checks everything
(post-apply). If a set — it checks only the objects introduced by those versions
(pre-apply prefix gate).
"""

import hashlib
import logging
import os
import sys
from pathlib import Path

import psycopg

from .config import settings
from .restore_identity import connection_identity_problems

log = logging.getLogger("avelren.schema_verify")

# --- Version-annotated physical contract ------------------------------------
# Format: (since_version | None, ...object details)
# since=None → always required (schema_migrations).
# The prefix gate in migrate.py filters by recorded_versions.

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

# Invariant-guarding indexes: we check the exact semantic definition —
# table + columns + partial predicate. The same name with different columns or a
# different WHERE is no longer the same invariant (e.g. "one pending" stops being
# guaranteed).
# (version, index_name, table, columns, predicate_expr_normalized)
_UNIQUE_PARTIAL_INDEXES_V: list[tuple[str, str, str, tuple[str, ...], str]] = [
    ("004_alerts", "alerts_one_pending_per_subscription", "alerts",
     ("subscription_id",), "(status = 'pending'::text)"),
    ("005_eta_targets", "eta_alerts_one_pending_per_target", "eta_alerts",
     ("target_id",), "(status = 'pending'::text)"),
    ("006_admin_devices", "health_alerts_one_open_per_kind", "health_alerts",
     ("kind",), "(resolved_at IS NULL)"),
]

# Regular (non-unique) indexes: existence check only.
_INDEXES_V: list[tuple[str, str]] = [
    ("008_notification_cancels", "notification_cancels_open_idx"),
]

# Named UNIQUE constraints. ON CONFLICT in the API relies on them directly;
# if a constraint was lost in the restore or has different columns — a POST fails.
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
    """Whether this object should be checked for the given set of recorded versions."""
    if recorded is None:
        return True
    if since is None:
        return True
    return since in recorded


# ---------------------------------------------------------------------------


def expected_migrations(directory: Path) -> dict[str, str]:
    """version → sha256 from the migration files (the source of truth for history)."""
    out: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql")):
        body = path.read_text(encoding="utf-8")
        out[path.stem] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return out


def verify_history(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Exact correspondence of the migration history to the files: none missing,
    no unknown/future versions, each SHA matches."""
    problems: list[str] = []
    expected = expected_migrations(directory)
    recorded = {
        row[0]: row[1]
        for row in conn.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
    }

    for version in expected.keys() - recorded.keys():
        problems.append(f"migration {version} is in the files but not recorded as applied")
    for version in recorded.keys() - expected.keys():
        problems.append(
            f"migration {version} is recorded but the file is missing (foreign/future version)"
        )
    for version in expected.keys() & recorded.keys():
        if expected[version] != recorded[version]:
            problems.append(f"migration {version}: the SHA in the DB does not match the file")
    return problems


def verify_contract(
    conn: psycopg.Connection,
    recorded_versions: set[str] | None = None,
) -> list[str]:
    """Physical schema: tables/columns/indexes/constraints/Timescale objects.

    recorded_versions=None → full check (post-apply, all objects).
    recorded_versions=set  → only objects introduced by those versions (pre-apply
    prefix gate: detect a corrupt restore BEFORE applying new files).
    """
    problems: list[str] = []
    def want(since: str | None) -> bool:
        return _want(since, recorded_versions)

    for since, table in _TABLES_V:
        if not want(since):
            continue
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{table}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"missing table/relation {table}")

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
            problems.append(f"missing column {table}.{column}")

    # Invariant indexes: exact semantic definition — the same name is not enough.
    # Someone could DROP+CREATE with the same name but different columns/predicate;
    # the invariant vanishes, and uniqueness+partial alone does not catch it.
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
            problems.append(f"missing index {index}")
            continue
        table_name, is_unique, is_partial, predicate, columns = row
        if table_name != want_table:
            problems.append(
                f"index {index} is on table {table_name}, expected {want_table}"
            )
        if not is_unique:
            problems.append(f"index {index} is not UNIQUE (invariant violated)")
        if not is_partial:
            problems.append(f"index {index} is not partial — no WHERE clause")
        actual_cols = tuple(columns or ())
        if actual_cols != want_cols:
            problems.append(
                f"index {index}: columns {actual_cols}, expected {want_cols}"
            )
        if is_partial and predicate != want_pred:
            problems.append(
                f"index {index}: predicate {predicate!r}, expected {want_pred!r}"
            )

    for since, index in _INDEXES_V:
        if not want(since):
            continue
        row = conn.execute("SELECT to_regclass(%s)", (f"public.{index}",)).fetchone()
        if not row or row[0] is None:
            problems.append(f"missing index {index}")

    # UNIQUE constraints: exact table + contype='u' + columns. The name alone is
    # not enough: a rename+recreate with different columns gives the same conname,
    # but ON CONFLICT (want_cols) would fail in prod.
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
            problems.append(f"missing constraint {constraint}")
            continue
        contype, table_name, columns = row
        if contype != "u":
            problems.append(
                f"constraint {constraint}: contype={contype!r}, expected 'u' (UNIQUE)"
            )
        if table_name != want_table:
            problems.append(
                f"constraint {constraint} is on table {table_name}, expected {want_table}"
            )
        actual_cols = tuple(columns or ())
        if actual_cols != want_cols:
            problems.append(
                f"constraint {constraint}: columns {actual_cols}, expected {want_cols}"
            )

    for since, ht in _HYPERTABLES_V:
        if not want(since):
            continue
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = %s",
            (ht,),
        ).fetchone()
        if not row:
            problems.append(f"{ht} is not a hypertable")

    for since, cagg in _CONTINUOUS_AGGREGATES_V:
        if not want(since):
            continue
        row = conn.execute(
            "SELECT 1 FROM timescaledb_information.continuous_aggregates WHERE view_name = %s",
            (cagg,),
        ).fetchone()
        if not row:
            problems.append(f"missing continuous aggregate {cagg}")

    return problems


def verify(conn: psycopg.Connection, directory: Path) -> list[str]:
    """Full check: history + physical contract for the versions actually recorded.

    The contract is filtered by recorded versions, not hard-coded over all _V
    entries: when `directory` contains only a prefix (a partial set of migrations,
    e.g. in tests), verify must not require objects of future migrations. A
    divergence between the files and what is recorded is caught by verify_history."""
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
    with psycopg.connect(settings.database_dsn, autocommit=True) as conn:
        expected_database = os.environ.get("AVELREN_RESTORE_VERIFY_TARGET")
        expected_role = os.environ.get("AVELREN_RESTORE_VERIFY_ROLE")
        if (expected_database is None) != (expected_role is None):
            problems = ["restore verification identity contract is incomplete"]
        elif expected_database is not None and expected_role is not None:
            problems = connection_identity_problems(conn, expected_database, expected_role)
        else:
            problems = []
        if not problems:
            problems = verify(conn, directory)
    if problems:
        log.error("the schema does NOT agree with the migration history:")
        for p in problems:
            log.error("  - %s", p)
        return 1
    log.info("schema agrees: %s migrations, contract intact", len(expected_migrations(directory)))
    return 0


if __name__ == "__main__":
    _dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/migrations")
    sys.exit(main(_dir))
