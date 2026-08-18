"""Migration applier.

Docker runs files from db/migrations only when creating an empty DB, so on an
already-populated prod, new migrations had to be applied by hand — and sooner or
later someone forgets, and prod diverges from the code.

Here each migration is applied exactly once, the fact is recorded in the DB, and
a run against an up-to-date database does nothing. Safe to call every deploy.

**A-07 — fail-closed.** Previously, with an empty `schema_migrations` but an
existing `checkpoints` table, the applier marked ALL files as applied on a
one-table heuristic. After a corrupt/old restore this produced a very
convincing lie: history says "001..NNN applied", while the structures are not
actually there. Now:

  * empty migrations directory → **FAIL CLOSED** (state cannot be proven);
  * clean DB (no known AvelRen object) → we create the history and apply
    everything;
  * valid history → prefix-gate + pre-apply physical check, then new files;
  * any AvelRen object exists but there is no trusted history → **FAIL CLOSED**.

Automatic baseline is gone. If a legacy DB without history ever needs to be
legitimized — that is a deliberate manual operator procedure (verify the
structure, insert rows into schema_migrations), not something that happens on
its own at deploy.

After applying, the schema is checked against the full contract
(`schema_verify`): if `schema_migrations` says one thing and the physical schema
another (e.g. the restore lost a column) — that too is exit 1.
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

# The full set of known AvelRen objects. The presence of ANY of them with an
# empty history is a sign of a legacy/partial state, not a clean DB. Looking at
# `checkpoints` alone is not enough: a corrupt restore could have
# `devices`/`alerts` without `checkpoints`.
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
        # An empty directory means /migrations did not mount, the path is wrong,
        # or the directory was deleted. Allowing the API to start on an unknown
        # schema is dangerous — fail closed.
        log.error("no migrations found in %s — stopping (fail-closed)", directory)
        return 1

    applied = 0
    with psycopg.connect(settings.database_dsn, autocommit=False) as conn:
        conn.execute(_SCHEMA)
        conn.commit()

        known = {
            row[0]: row[1]
            for row in conn.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
        }

        # A-07 fail-closed: history is empty — we decide by the actual state of
        # the schema, not by a single table.
        if not known:
            existing = _existing_objects(conn)
            if existing:
                log.error(
                    "An AvelRen schema exists in the DB (%s), but there is no trusted "
                    "migration history. Automatic baseline is forbidden (A-07): an "
                    "unknown/partial state cannot be declared applied. If this is a "
                    "known legacy DB — legitimize the baseline manually per the runbook, "
                    "verifying the structure.",
                    ", ".join(existing),
                )
                return 1
            log.info("clean DB — applying all migrations from scratch")

        # A-07 prefix gate: if something is already recorded, we check that what
        # is recorded is a valid contiguous prefix of the files — with no gap and
        # no future versions. Only then (and only with a valid prefix) do we check
        # the physical schema, to detect a corrupt restore BEFORE new files apply.
        if known:
            sorted_stems = [f.stem for f in files]
            known_set = set(known.keys())

            future = known_set - set(sorted_stems)
            if future:
                log.error(
                    "the DB records unknown/future migrations (files not in the repo): %s",
                    ", ".join(sorted(future)),
                )
                return 1

            n = len(known_set)
            expected_prefix = {sorted_stems[i] for i in range(n)}
            gaps = expected_prefix - known_set
            if gaps:
                log.error(
                    "the recorded history has gaps (missing from the first prefix): %s",
                    ", ".join(sorted(gaps)),
                )
                return 1

            # Physical contract for the current prefix — before applying new files.
            pre_problems = schema_verify.verify_contract(conn, recorded_versions=known_set)
            if pre_problems:
                log.error(
                    "the physical schema contradicts the recorded PREFIX history "
                    "(A-07, before new migrations):"
                )
                for p in pre_problems:
                    log.error("  - %s", p)
                return 1

        for path in files:
            version = path.stem
            body = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

            if version in known:
                if known[version] != digest:
                    # A silent mismatch is worse than a crash: it means an
                    # already-applied file was changed, and the DB no longer
                    # matches the code.
                    log.error(
                        "migration %s was changed after being applied — fix it manually", version
                    )
                    return 1
                continue

            log.info("applying %s", version)
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
                log.error("migration %s failed: %s", version, exc)
                return 1

        # Full post-apply verify: history + physical contract of all versions.
        problems = schema_verify.verify(conn, directory)
        if problems:
            log.error("the schema contradicts the migration history (A-07):")
            for p in problems:
                log.error("  - %s", p)
            return 1

    log.info("done: applied %s, total %s", applied, len(files))
    return 0


if __name__ == "__main__":
    # Optional argument — the path to migrations: in the container it is
    # /migrations, while CI runs it from the repository root.
    sys.exit(run(Path(sys.argv[1]) if len(sys.argv) > 1 else MIGRATIONS_DIR))
