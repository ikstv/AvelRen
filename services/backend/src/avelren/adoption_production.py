"""Production adoption coordination; no CLI or runtime/service mutation."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg

from . import privilege_gate
from .adoption_inventory import AdoptionError, _capture_catalog, capture, fingerprint
from .adoption_operation import (
    PHASES,
    OperationManifest,
    read_operation,
    require_production_evidence,
    verify_receipt,
    write_receipt,
)
from .adoption_operator import FORBIDDEN_ENVIRONMENT, Confirmation, verify_confirmation
from .adoption_plan import AdoptionPlan, decode_plan, encode_plan, plan_digest
from .adoption_preflight import require_quiescent
from .adoption_target import TargetBinding, target_digest, verify_target
from .adoption_transaction import READ_OPTIONS, run_mutation
from .postgres_adoption import AdoptionResult


@dataclass(frozen=True)
class MaintenanceContext:
    operation_id: str
    target_digest: str
    plan_digest: str
    runtime_digest: str
    phase: str


class RuntimeVerifier(Protocol):
    """Adapter must recheck actual runtime and the provenance of checkout roots."""

    def verify(self, context: MaintenanceContext, manifest: OperationManifest) -> None: ...

    def checkout_roots(self) -> tuple[Path, ...]: ...


def _close_guard(conn):
    try:
        conn.close()
        return True
    except Exception:
        return False


@dataclass
class _LifecycleLock:
    """Database-wide production serialization, independent of mutation COMMIT.

    The fixed maintenance database keeps this session out of target quiescence
    checks. Operation IDs, evidence paths, plans and roles do not split its key.
    """

    conn: psycopg.Connection
    key: int
    possible_commit: bool = False

    @classmethod
    def acquire(cls, dsn, binding):
        identity = (
            f"avelren-production-adoption-v1:{binding.system_identifier}:{binding.database_oid}"
        )
        key = int.from_bytes(hashlib.sha256(identity.encode("ascii")).digest()[:8], signed=True)
        try:
            conn = psycopg.connect(
                dsn, dbname="postgres", autocommit=True, connect_timeout=10, options=READ_OPTIONS
            )
        except Exception:
            raise AdoptionError("production_lock_unavailable") from None
        try:
            actual = conn.execute(
                "SELECT c.system_identifier::text, session_user, d.datname, d.oid, "
                "current_database() FROM pg_catalog.pg_control_system() AS c "
                "CROSS JOIN pg_catalog.pg_database AS d WHERE d.datname = %s",
                (binding.database,),
            ).fetchone()
            if actual != (
                binding.system_identifier,
                binding.session_role,
                binding.database,
                binding.database_oid,
                "postgres",
            ):
                raise AdoptionError("target_mismatch")
            if conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone() != (True,):
                raise AdoptionError("production_operation_busy")
            return cls(conn, key)
        except BaseException as exc:
            closed = _close_guard(conn)
            if not isinstance(exc, Exception):
                raise
            if not closed:
                raise AdoptionError("production_lock_release_unavailable") from None
            if isinstance(exc, AdoptionError):
                raise
            raise AdoptionError("production_lock_unavailable") from None

    def verify(self):
        try:
            # Inspect the held 64-bit key; reacquiring would increment its count
            # and could silently reacquire a lost lock after a competing inverse.
            held = self.conn.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_locks "
                "WHERE locktype='advisory' AND pid=pg_backend_pid() "
                "AND database=(SELECT oid FROM pg_catalog.pg_database "
                "WHERE datname=current_database()) AND classid=%s::oid AND objid=%s::oid "
                "AND objsubid=1 AND mode='ExclusiveLock' AND granted)",
                ((self.key >> 32) & 0xFFFFFFFF, self.key & 0xFFFFFFFF),
            ).fetchone()
            if held != (True,):
                raise AdoptionError("production_lock_unavailable")
        except Exception:
            raise AdoptionError("production_lock_unavailable") from None

    def release(self):
        released = False
        try:
            released = self.conn.execute(
                "SELECT pg_advisory_unlock(%s)", (self.key,)
            ).fetchone() == (True,)
        except Exception:
            pass
        finally:
            closed = _close_guard(self.conn)
        return released and closed


def _runtime_gate(runtime, context, manifest, directory):
    try:
        if runtime.verify(context, manifest) is not None:
            raise AdoptionError("runtime_verifier_contract")
        roots = runtime.checkout_roots()
    except AdoptionError:
        raise
    except Exception:
        raise AdoptionError("runtime_unverified") from None
    require_production_evidence(directory, checkout_roots=roots)


def _records(directory, manifest):
    present = set()
    for phase in PHASES:
        try:
            # Unlike exists(), lstat does not silently ignore a dangling symlink.
            (directory / f"production-{phase}.json").lstat()
        except FileNotFoundError:
            continue
        verify_receipt(directory, phase, manifest)
        present.add(phase)
    if present & {"inverse-intent", "inverse-committed", "inverse-accepted"}:
        raise AdoptionError("incomplete_evidence")
    if present not in (
        set(),
        {"apply-intent"},
        {"apply-intent", "committed"},
        {"apply-intent", "committed", "accepted"},
    ):
        raise AdoptionError("incomplete_evidence")
    return present


def _verify_chain(directory, manifest, phases):
    if read_operation(directory) != manifest:
        raise AdoptionError("operation_drift")
    for phase in phases:
        verify_receipt(directory, phase, manifest)


def _authority(binding, plan, directory, context, confirmation, runtime, inverse):
    if any(name in os.environ for name in FORBIDDEN_ENVIRONMENT):
        raise AdoptionError("production_test_environment")
    manifest = read_operation(directory)
    if not isinstance(context, MaintenanceContext) or context != MaintenanceContext(
        manifest.operation_id,
        manifest.target_digest,
        manifest.plan_digest,
        binding.runtime_digest,
        "quiescent",
    ):
        raise AdoptionError("maintenance_context")
    if (
        manifest.target_digest != target_digest(binding)
        or manifest.plan_digest != plan_digest(plan)
        or manifest.before_fingerprint != fingerprint(plan.before)
        or manifest.expected_fingerprint != fingerprint(plan.expected)
        or binding.database != plan.before.database
        or binding.database != plan.expected.database
    ):
        raise AdoptionError("operation_plan_mismatch")
    verify_confirmation(confirmation, "INVERSE" if inverse else "ADOPT", manifest)
    _runtime_gate(runtime, context, manifest, directory)
    # Regenerate every statement before opening a database connection.
    plan = decode_plan(encode_plan(plan))
    records = _records(directory, manifest)
    if inverse:
        if not {"apply-intent", "committed"} <= records:
            raise AdoptionError("incomplete_evidence")
    elif records and "accepted" not in records:
        raise AdoptionError("incomplete_evidence")
    return manifest, plan, records


def _read_state(dsn, binding, *, gate=False):
    with psycopg.connect(dsn, connect_timeout=10, options=READ_OPTIONS) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        verify_target(conn, binding)
        require_quiescent(conn)
        actual = fingerprint(capture(conn))
        failures = (
            privilege_gate.audit(conn, Path(__file__).resolve().parents[4] / "db/migrations")
            if gate
            else []
        )
        return actual, failures


def _coordinate(dsn, binding, plan, directory, context, confirmation, runtime, *, inverse):
    manifest, plan, records = _authority(
        binding, plan, directory, context, confirmation, runtime, inverse
    )
    if not isinstance(dsn, str) or not dsn.strip():
        raise AdoptionError("required_connection_environment")
    guard = _LifecycleLock.acquire(dsn, binding)
    try:
        # Authority was read before acquiring the guard. Never use an earlier
        # record set if another lifecycle completed during those initial reads.
        _verify_chain(directory, manifest, records)
        if _records(directory, manifest) != records:
            raise AdoptionError("incomplete_evidence")
        result = _coordinate_locked(
            dsn,
            binding,
            plan,
            directory,
            context,
            runtime,
            manifest,
            records,
            guard,
            inverse=inverse,
        )
    except BaseException as exc:
        released = guard.release()
        if not isinstance(exc, Exception):
            raise
        if guard.possible_commit:
            return AdoptionResult(
                "commit_unknown",
                "production_operation_unverified",
                manifest.before_fingerprint,
                None,
            )
        if not released:
            raise AdoptionError("production_lock_release_unavailable") from None
        raise
    if not guard.release():
        if guard.possible_commit:
            if result.status == "commit_unknown":
                return result
            return AdoptionResult(
                "commit_unknown",
                "production_lock_release_unavailable",
                manifest.before_fingerprint,
                None,
            )
        if result.status == "rollback_failed":
            return result
        if result.status == "rolled_back":
            return AdoptionResult(
                "rollback_failed",
                "production_lock_release_unavailable",
                manifest.before_fingerprint,
                result.after_fingerprint,
            )
        raise AdoptionError("production_lock_release_unavailable")
    return result


def _coordinate_locked(
    dsn,
    binding,
    plan,
    directory,
    context,
    runtime,
    manifest,
    records,
    guard,
    *,
    inverse,
):
    before = manifest.before_fingerprint
    expected = manifest.expected_fingerprint
    source, target = (expected, before) if inverse else (before, expected)
    actual, _ = _read_state(dsn, binding)
    if not inverse and records:
        if actual != expected:
            raise AdoptionError("receipt_drift")
        if _records(directory, manifest) != records:
            raise AdoptionError("incomplete_evidence")
        _verify_chain(directory, manifest, records)
        return AdoptionResult("already_target", None, before, actual)
    if actual != source:
        raise AdoptionError("inverse_drift" if inverse else "plan_drift")
    intent = "inverse-intent" if inverse else "apply-intent"

    def gates(conn):
        _runtime_gate(runtime, context, manifest, directory)
        verify_target(conn, binding)
        require_quiescent(conn)
        if read_operation(directory) != manifest:
            raise AdoptionError("operation_drift")
        guard.verify()

    def before_write(conn):
        gates(conn)
        # Recheck authority after serialization: a concurrent operation may
        # have published evidence while this connection waited on the lock.
        if _records(directory, manifest) != records:
            raise AdoptionError("incomplete_evidence")
        if fingerprint(_capture_catalog(conn)) != source:
            raise AdoptionError("inverse_drift" if inverse else "plan_drift")
        write_receipt(directory, intent, manifest, category=None)

    def before_commit(conn):
        gates(conn)
        _verify_chain(directory, manifest, records | {intent})

    guard.possible_commit = True
    try:
        outcome = run_mutation(
            dsn,
            plan,
            direction="inverse" if inverse else "forward",
            before_write=before_write,
            before_commit=before_commit,
        )
    except AdoptionError:
        # The shared engine raises categorical refusals only after confirmed
        # rollback/close without an attempted ownership/ACL statement.
        guard.possible_commit = False
        raise
    guard.possible_commit = outcome.status in {"committed", "commit_unknown"}
    if outcome.status != "committed":
        # For a failed inverse, engine rolled_back means its SQL was rolled
        # back to expected, not that production was restored to plan.before.
        status = (
            "rollback_failed" if inverse and outcome.status == "rolled_back" else outcome.status
        )
        return AdoptionResult(status, outcome.category, before, outcome.fingerprint)
    try:
        guard.verify()
        write_receipt(
            directory, "inverse-committed" if inverse else "committed", manifest, category=None
        )
    except Exception:
        return AdoptionResult("commit_unknown", "committed_receipt_unavailable", before, None)
    try:
        _runtime_gate(runtime, context, manifest, directory)
        actual, failures = _read_state(dsn, binding, gate=not inverse)
        _verify_chain(
            directory,
            manifest,
            records | {intent, "inverse-committed" if inverse else "committed"},
        )
        if actual != target:
            return AdoptionResult("rollback_failed", "committed_drift", before, actual)
        if failures:
            return AdoptionResult("rollback_failed", "acceptance_failed", before, actual)
        guard.verify()
        write_receipt(
            directory, "inverse-accepted" if inverse else "accepted", manifest, category=None
        )
        guard.verify()
        return AdoptionResult("rolled_back" if inverse else "adopted", None, before, actual)
    except Exception:
        return AdoptionResult("commit_unknown", "post_commit_unverified", before, None)


def _run(dsn, binding, plan, evidence_dir, context, confirmation, runtime, *, inverse):
    try:
        return _coordinate(
            dsn, binding, plan, evidence_dir, context, confirmation, runtime, inverse=inverse
        )
    except AdoptionError as exc:
        # Private I/O and libpq may attach sensitive causes. Publish only the
        # categorical refusal, including when callers format a traceback.
        raise AdoptionError(exc.category) from None
    except Exception:
        raise AdoptionError("production_unavailable") from None


def apply_production(
    dsn: str,
    binding: TargetBinding,
    plan: AdoptionPlan,
    evidence_dir: Path,
    context: MaintenanceContext,
    confirmation: Confirmation,
    runtime: RuntimeVerifier,
) -> AdoptionResult:
    """Apply an already manifested operation with a fresh maintenance proof."""
    return _run(dsn, binding, plan, evidence_dir, context, confirmation, runtime, inverse=False)


def inverse_production(
    dsn: str,
    binding: TargetBinding,
    plan: AdoptionPlan,
    evidence_dir: Path,
    context: MaintenanceContext,
    confirmation: Confirmation,
    runtime: RuntimeVerifier,
) -> AdoptionResult:
    """Explicitly reverse a proven commit; never infer authorization from acceptance."""
    return _run(dsn, binding, plan, evidence_dir, context, confirmation, runtime, inverse=True)
