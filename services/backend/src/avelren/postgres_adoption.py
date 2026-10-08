"""Disposable-only adoption executor; production operations are deliberately absent."""

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from . import privilege_gate
from .adoption_evidence import read_private, read_verified, write_private
from .adoption_inventory import (
    AdoptionError,
    _capture_catalog,
    capture,
    decode,
    encode,
    fingerprint,
)
from .adoption_plan import AdoptionPlan, build_plan, decode_plan, encode_plan, plan_digest

READ_OPTIONS = "-c default_transaction_read_only=on -c statement_timeout=30000"
WRITE_OPTIONS = (
    "-c default_transaction_read_only=off -c lock_timeout=10000 -c statement_timeout=30000"
)
FAILPOINTS = {None, "before_commit", "after_commit", "during_inverse", "receipt_write"}


@dataclass(frozen=True)
class AdoptionResult:
    status: str
    category: str | None
    before_fingerprint: str
    after_fingerprint: str | None


def read_snapshot(dsn):
    with psycopg.connect(dsn, connect_timeout=10, options=READ_OPTIONS) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return capture(conn)


def _record(directory, name, record):
    return write_private(
        directory, name, json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    )


def _load_record(directory, name):
    value = json.loads(read_private(directory, name))
    if not isinstance(value, dict):
        raise AdoptionError("receipt_format")
    return value


def _guards(dsn, target, plan, failpoint):
    if (
        os.environ.get("AVELREN_DATABASE_TEST") != "1"
        or not re.fullmatch(r"avelren_case_[0-9a-f]{32}_test", target)
        or conninfo_to_dict(dsn).get("dbname") != target
        or plan.before.database != target
        or failpoint not in FAILPOINTS
    ):
        raise AdoptionError("disposable_target_required")
    # Re-generation validates every SQL statement, including direct API calls.
    decode_plan(encode_plan(plan))


def _lock(conn, target):
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    if conn.info.dbname != target:
        raise AdoptionError("database_identity")
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(current_database() "
        "|| ':avelren-adoption-016',0))"
    )
    if conn.execute(
        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=%s "
        "AND pid<>pg_backend_pid() AND backend_type='client backend')",
        (target,),
    ).fetchone()[0]:
        raise AdoptionError("active_sessions")
    for name in sorted(set(privilege_gate.TABLES) - {"observations_hourly"}):
        conn.execute(
            sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
                sql.Identifier("public", name),
            )
        )


def _run_gate(dsn):
    with psycopg.connect(dsn, connect_timeout=10, options=READ_OPTIONS) as conn:
        return privilege_gate.audit(conn, Path(__file__).resolve().parents[4] / "db/migrations")


def _inverse(dsn, target, plan, directory, *, failpoint):
    _guards(dsn, target, plan, failpoint)
    desired = fingerprint(plan.before)
    current = fingerprint(plan.expected)
    try:
        with psycopg.connect(dsn, connect_timeout=10, options=WRITE_OPTIONS) as conn:
            _lock(conn, target)
            if fingerprint(_capture_catalog(conn)) != current:
                raise AdoptionError("inverse_drift")
            _record(
                directory,
                "inverse-intent.json",
                {"plan_sha256": plan_digest(plan), "from": current, "to": desired},
            )
            for index, statement in enumerate(plan.inverse):
                conn.execute(statement)
                if failpoint == "during_inverse" and index == 0:
                    raise AdoptionError("test_inverse_failure")
            if fingerprint(_capture_catalog(conn)) != desired:
                raise AdoptionError("inverse_verification")
            conn.commit()
        restored = fingerprint(read_snapshot(dsn))
        if restored != desired:
            raise AdoptionError("inverse_verification")
        result = AdoptionResult("rolled_back", "post_commit_acceptance", desired, restored)
        _record(directory, "rolled-back.json", asdict(result))
        return result
    except (psycopg.Error, AdoptionError, OSError):
        return AdoptionResult("rollback_failed", "inverse_unverified", desired, None)


def apply_disposable(
    dsn: str, target: str, plan: AdoptionPlan, evidence_dir: Path, *, failpoint: str | None = None
) -> AdoptionResult:
    _guards(dsn, target, plan, failpoint)
    before = fingerprint(plan.before)
    expected = fingerprint(plan.expected)
    directory = Path(evidence_dir)
    actual = fingerprint(read_snapshot(dsn))
    if (directory / "apply-intent.json").exists():
        if not (directory / "accepted.json").is_file():
            raise AdoptionError("incomplete_evidence")
        receipt = _load_record(directory, "accepted.json")
        committed = _load_record(directory, "committed.json")
        if (
            receipt.get("status") != "adopted"
            or receipt.get("before_fingerprint") != before
            or receipt.get("category") is not None
            or receipt.get("after_fingerprint") != expected
            or committed.get("plan_sha256") != plan_digest(plan)
            or committed.get("before_fingerprint") != before
            or committed.get("after_fingerprint") != expected
            or actual != expected
        ):
            raise AdoptionError("receipt_drift")
        return AdoptionResult("already_target", None, before, actual)
    if actual == expected and not plan.forward:
        return AdoptionResult("already_target", None, before, actual)
    if actual != before:
        raise AdoptionError("plan_drift")
    with psycopg.connect(dsn, connect_timeout=10, options=WRITE_OPTIONS) as conn:
        _lock(conn, target)
        if fingerprint(_capture_catalog(conn)) != before:
            raise AdoptionError("plan_drift")
        _record(
            directory,
            "apply-intent.json",
            {
                "format_version": 1,
                "database": target,
                "plan_sha256": plan_digest(plan),
                "before_fingerprint": before,
                "expected_fingerprint": expected,
            },
        )
        try:
            for statement in plan.forward:
                conn.execute(statement)
            if failpoint == "before_commit":
                raise AdoptionError("test_before_commit")
            if fingerprint(_capture_catalog(conn)) != expected:
                raise AdoptionError("forward_verification")
            conn.commit()
        except (psycopg.Error, AdoptionError):
            conn.rollback()
            restored = fingerprint(read_snapshot(dsn))
            if restored != before:
                return AdoptionResult("rollback_failed", "pre_commit_unverified", before, restored)
            result = AdoptionResult("rolled_back", "pre_commit_failure", before, restored)
            _record(directory, "rolled-back.json", asdict(result))
            return result
    try:
        if failpoint == "receipt_write":
            raise AdoptionError("test_receipt_failure")
        _record(
            directory,
            "committed.json",
            {
                "format_version": 1,
                "plan_sha256": plan_digest(plan),
                "before_fingerprint": before,
                "after_fingerprint": expected,
            },
        )
    except (OSError, AdoptionError):
        return AdoptionResult("commit_unknown", "committed_receipt_unavailable", before, None)
    try:
        if fingerprint(read_snapshot(dsn)) != expected:
            return AdoptionResult("rollback_failed", "committed_drift", before, None)
        if failpoint in {"after_commit", "during_inverse"} or _run_gate(dsn):
            return _inverse(dsn, target, plan, directory, failpoint=failpoint)
        result = AdoptionResult("adopted", None, before, expected)
        _record(directory, "accepted.json", asdict(result))
        return result
    except (psycopg.Error, OSError, AdoptionError):
        # Commit happened. Missing acceptance evidence is never reported as rollback/success.
        return AdoptionResult("commit_unknown", "post_commit_unverified", before, None)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AdoptionError("invalid_arguments")


def _load_snapshot(directory):
    digest = read_private(directory, "snapshot.sha256").decode()
    return decode(read_verified(directory, "snapshot.json", digest))


def _load_plan(directory):
    digest = read_private(directory, "plan.sha256").decode()
    return decode_plan(read_verified(directory, "plan.json", digest))


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(add_help=False)
        subparsers = parser.add_subparsers(dest="command", required=True)
        subparsers.add_parser("inventory", add_help=False).add_argument(
            "--output-dir", required=True
        )
        for command in ("plan", "apply-test", "inspect"):
            subparsers.add_parser(command, add_help=False).add_argument(
                "--evidence-dir", required=True
            )
        args = parser.parse_args(argv)
        directory = Path(args.output_dir if args.command == "inventory" else args.evidence_dir)
        if args.command == "plan":
            plan = build_plan(_load_snapshot(directory))
            digest = write_private(directory, "plan.json", encode_plan(plan))
            write_private(directory, "plan.sha256", digest.encode())
            result = AdoptionResult(
                "planned", None, fingerprint(plan.before), fingerprint(plan.expected)
            )
        else:
            dsn = os.environ.get("AVELREN_ADOPTION_DSN")
            target = os.environ.get("AVELREN_ADOPTION_TARGET")
            if not dsn or not target:
                raise AdoptionError("required_connection_environment")
            if args.command == "inventory":
                snapshot = read_snapshot(dsn)
                if snapshot.database != target:
                    raise AdoptionError("database_identity")
                digest = write_private(directory, "snapshot.json", encode(snapshot))
                write_private(directory, "snapshot.sha256", digest.encode())
                result = AdoptionResult("inventoried", None, digest, digest)
            else:
                plan = _load_plan(directory)
                if args.command == "apply-test":
                    result = apply_disposable(
                        dsn,
                        target,
                        plan,
                        directory,
                        failpoint=os.environ.get("AVELREN_ADOPTION_TEST_FAILPOINT"),
                    )
                else:
                    snapshot = read_snapshot(dsn)
                    if snapshot.database != target or plan.before.database != target:
                        raise AdoptionError("database_identity")
                    actual = fingerprint(snapshot)
                    state = (
                        "before"
                        if actual == fingerprint(plan.before)
                        else ("target" if actual == fingerprint(plan.expected) else "drift")
                    )
                    result = AdoptionResult("inspected", state, fingerprint(plan.before), actual)
        print(json.dumps(asdict(result), sort_keys=True))
        return {"rolled_back": 1, "rollback_failed": 3, "commit_unknown": 4}.get(result.status, 0)
    except AdoptionError as exc:
        print("adoption refused: " + exc.category, file=sys.stderr)
        return 2 if exc.category in {"invalid_arguments", "required_connection_environment"} else 1
    except (psycopg.Error, OSError, ValueError, TypeError, RecursionError):
        print("adoption unavailable", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
