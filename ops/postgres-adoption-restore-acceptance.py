"""Synthetic restore → adoption → verified inverse in the disposable restore project."""

import os
import tempfile
from pathlib import Path

import psycopg
from avelren.adoption_inventory import fingerprint
from avelren.adoption_plan import build_plan
from avelren.postgres_adoption import _inverse, apply_disposable, read_snapshot


def preserved(dsn):
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
        return (
            conn.execute(
                "SELECT * FROM observations ORDER BY time,checkpoint_id"
            ).fetchall(),
            conn.execute(
                "SELECT * FROM observations_hourly ORDER BY bucket,checkpoint_id"
            ).fetchall(),
            conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall(),
            conn.execute("SELECT * FROM surge_alerts ORDER BY id").fetchall(),
            conn.execute(
                "SELECT * FROM surge_delivery_attempts ORDER BY id"
            ).fetchall(),
        )


def main():
    dsn = os.environ["AVELREN_ADOPTION_DSN"]
    target = os.environ["AVELREN_ADOPTION_TARGET"]
    if os.environ.get("AVELREN_DATABASE_TEST") != "1":
        raise RuntimeError("disposable acceptance required")
    # Validate a canonical no-op plan/target before the fixture's intentional drift.
    initial = read_snapshot(dsn)
    with tempfile.TemporaryDirectory(prefix="avelren-adoption-restore-") as directory:
        assert apply_disposable(
            dsn, target, build_plan(initial), Path(directory) / "initial"
        ).status in {
            "adopted",
            "already_target",
        }
    data = preserved(dsn)
    assert data[0], "restored observations absent"
    assert data[1], "restored aggregate absent"
    assert len(data[2]) == 16, "restored journal differs"
    assert any(row["kind"] == "compressed_relation" for row in initial.sections["topology"])
    with psycopg.connect(dsn) as conn:
        conn.execute("GRANT SELECT ON observations TO PUBLIC")
    before = read_snapshot(dsn)
    plan = build_plan(before)
    with tempfile.TemporaryDirectory(prefix="avelren-adoption-restore-") as directory:
        evidence = Path(directory) / "proof"
        result = apply_disposable(dsn, target, plan, evidence)
        assert result.status == "adopted", result
        assert preserved(dsn) == data
        inverse = _inverse(dsn, target, plan, evidence, failpoint=None)
        assert inverse.status == "rolled_back", inverse
        assert fingerprint(read_snapshot(dsn)) == fingerprint(before)
        assert preserved(dsn) == data
    print(
        "Synthetic restored database adoption/inverse: PASS; data and journal unchanged"
    )


if __name__ == "__main__":
    main()
