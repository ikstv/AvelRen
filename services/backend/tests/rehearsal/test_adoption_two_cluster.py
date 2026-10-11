"""Two owned, isolated Timescale clusters must not share adoption authority."""

import os
import re
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from services.backend.tests.database.test_adoption_production import (
    _content_digest,
    _pause_fixture_jobs,
)

from avelren.adoption_inventory import AdoptionError, encode, fingerprint
from avelren.adoption_operation import make_operation, write_operation
from avelren.adoption_operator import Confirmation
from avelren.adoption_plan import build_plan, plan_digest
from avelren.adoption_production import MaintenanceContext, apply_production
from avelren.adoption_target import capture_target, verify_target
from avelren.adoption_transaction import read_snapshot


def test_adoption_two_cluster_target_refusal_preserves_both_clusters(tmp_path, monkeypatch):
    # Missing runner infrastructure must fail instead of silently skipping acceptance.
    assert os.environ.get("AVELREN_PRODUCTION_REHEARSAL") == "1", "two owned clusters required"
    name = os.environ["AVELREN_PRODUCTION_REHEARSAL_NAME"]
    assert re.fullmatch(r"avelren_case_[0-9a-f]{32}_test", name)
    source_commit = os.environ["AVELREN_PRODUCTION_REHEARSAL_COMMIT"]
    assert re.fullmatch(r"[0-9a-f]{40}", source_commit)
    dsns = tuple(
        f"postgresql://avelren_admin:ci-only@{host}:5432/{name}"
        for host in ("test-db", "second-test-db")
    )
    for host, dsn in zip(("test-db", "second-test-db"), dsns, strict=True):
        assert conninfo_to_dict(dsn) == {
            "user": "avelren_admin",
            "password": "ci-only",
            "host": host,
            "port": "5432",
            "dbname": name,
        }
        with psycopg.connect(dsn) as conn:
            # Fresh synthetic fixtures only: independent migration runs otherwise
            # differ in applied_at. Never normalize a restored/production journal.
            conn.execute("UPDATE schema_migrations SET applied_at='2026-10-11T00:00:00Z'")
            _pause_fixture_jobs(conn)
            conn.execute("ALTER TABLE devices OWNER TO avelren_admin")
            conn.execute("GRANT SELECT ON devices TO PUBLIC")
            conn.execute(
                "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'Synthetic',1)"
            )
            conn.execute(
                "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,"
                "is_paused,wait_time_status) VALUES('2026-10-01T00:00:00Z',17,3600,20,"
                "false,'reported')"
            )
    snapshots = tuple(read_snapshot(dsn) for dsn in dsns)
    journals = tuple(snapshot.sections["journal"] for snapshot in snapshots)
    assert len(journals[0]) == len(journals[1]) == 16
    assert journals[0] == journals[1]
    plans = tuple(build_plan(snapshot) for snapshot in snapshots)
    assert encode(snapshots[0]) == encode(snapshots[1])
    assert plan_digest(plans[0]) == plan_digest(plans[1])
    data = tuple(_content_digest(dsn) for dsn in dsns)
    bindings = []
    for dsn in dsns:
        with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as conn:
            bindings.append(
                capture_target(conn, source_commit=source_commit, runtime_digest="b" * 64)
            )
    first, second = bindings
    assert first.database == second.database == name
    assert first.system_identifier != second.system_identifier
    with psycopg.connect(dsns[1], options="-c default_transaction_read_only=on") as conn:
        with pytest.raises(AdoptionError, match="^target_mismatch$"):
            verify_target(conn, first)
    manifest = make_operation(first, plans[0])
    evidence = tmp_path / "evidence"
    write_operation(evidence, manifest)
    context = MaintenanceContext(
        manifest.operation_id,
        manifest.target_digest,
        manifest.plan_digest,
        first.runtime_digest,
        "quiescent",
    )
    confirmation = Confirmation(
        "ADOPT", manifest.operation_id, manifest.target_digest, manifest.plan_digest
    )

    class FixtureRuntime:
        def verify(self, context, operation):
            assert operation == manifest

        def checkout_roots(self):
            return (Path(__file__).resolve().parents[4],)

    # Only these canonical disposable DSNs exist here. The real API has no test bypass.
    assert os.environ.get("AVELREN_DATABASE_TEST") == "1"
    with monkeypatch.context() as isolated:
        isolated.delenv("AVELREN_DATABASE_TEST")
        isolated.delenv("AVELREN_ADOPTION_TEST_FAILPOINT", raising=False)
        with pytest.raises(AdoptionError, match="^target_mismatch$"):
            apply_production(
                dsns[1], first, plans[0], evidence, context, confirmation, FixtureRuntime()
            )
    assert not (evidence / "production-apply-intent.json").exists()
    for index, dsn in enumerate(dsns):
        assert fingerprint(read_snapshot(dsn)) == fingerprint(snapshots[index])
        assert _content_digest(dsn) == data[index]
