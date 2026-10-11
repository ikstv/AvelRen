"""Operation-bound, private production evidence; no database or runtime mutation."""

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .adoption_evidence import read_private, read_verified, write_private
from .adoption_inventory import AdoptionError, fingerprint
from .adoption_plan import AdoptionPlan, plan_digest
from .adoption_target import TargetBinding, target_digest

PHASES = (
    "apply-intent",
    "committed",
    "accepted",
    "inverse-intent",
    "inverse-committed",
    "inverse-accepted",
)


@dataclass(frozen=True)
class OperationManifest:
    format_version: int
    operation_id: str
    target_digest: str
    plan_digest: str
    before_fingerprint: str
    expected_fingerprint: str


def _validate(manifest: OperationManifest) -> None:
    if (
        not isinstance(manifest, OperationManifest)
        or type(manifest.format_version) is not int
        or manifest.format_version != 1
        or not isinstance(manifest.operation_id, str)
        or re.fullmatch(r"[0-9a-f]{32}", manifest.operation_id) is None
        or any(
            not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (
                manifest.target_digest,
                manifest.plan_digest,
                manifest.before_fingerprint,
                manifest.expected_fingerprint,
            )
        )
    ):
        raise AdoptionError("operation_format")


def _canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _object(payload: bytes, category: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AdoptionError(category)
            result[key] = value
        return result

    try:
        record = json.loads(payload, object_pairs_hook=unique)
        if not isinstance(record, dict):
            raise AdoptionError(category)
        return record
    except (ValueError, TypeError, UnicodeError):
        raise AdoptionError(category) from None


def make_operation(binding: TargetBinding, plan: AdoptionPlan) -> OperationManifest:
    digest = target_digest(binding)
    if (
        type(plan.format_version) is not int
        or plan.format_version != 1
        or binding.database != plan.before.database
        or binding.database != plan.expected.database
    ):
        raise AdoptionError("operation_plan_mismatch")
    return OperationManifest(
        1,
        uuid.uuid4().hex,
        digest,
        plan_digest(plan),
        fingerprint(plan.before),
        fingerprint(plan.expected),
    )


def encode_operation(manifest: OperationManifest) -> bytes:
    _validate(manifest)
    return _canonical(asdict(manifest))


def decode_operation(payload: bytes) -> OperationManifest:
    record = _object(payload, "operation_format")
    if set(record) != set(OperationManifest.__dataclass_fields__):
        raise AdoptionError("operation_format")
    manifest = OperationManifest(**record)
    _validate(manifest)
    return manifest


def write_operation(directory: Path, manifest: OperationManifest) -> None:
    digest = write_private(directory, "production-operation.json", encode_operation(manifest))
    # A missing sidecar leaves an unusable operation. Neither artifact is overwritten
    # on resume, including when publication of the second file is interrupted.
    write_private(directory, "production-operation.sha256", (digest + "\n").encode("ascii"))


def read_operation(directory: Path) -> OperationManifest:
    checksum = read_private(directory, "production-operation.sha256")
    if re.fullmatch(rb"[0-9a-f]{64}\n", checksum) is None:
        raise AdoptionError("operation_checksum")
    payload = read_verified(directory, "production-operation.json", checksum[:-1].decode("ascii"))
    return decode_operation(payload)


def _receipt(phase: str, manifest: OperationManifest, category: str | None) -> dict:
    _validate(manifest)
    if phase not in PHASES or category is not None:
        # These phases attest successful intent/commit/acceptance only. Failure
        # categories belong to the coordinator's result, never an accepted receipt.
        raise AdoptionError("receipt_format")
    return {**asdict(manifest), "phase": phase, "category": category}


def write_receipt(
    directory: Path, phase: str, manifest: OperationManifest, *, category: str | None
) -> None:
    record = _receipt(phase, manifest, category)
    write_private(directory, f"production-{phase}.json", _canonical(record))


def verify_receipt(directory: Path, phase: str, manifest: OperationManifest) -> None:
    expected = _receipt(phase, manifest, None)
    actual = _object(read_private(directory, f"production-{phase}.json"), "receipt_format")
    if set(actual) != set(expected):
        raise AdoptionError("receipt_format")
    decode_operation(_canonical({key: actual[key] for key in asdict(manifest)}))
    if actual != expected:
        raise AdoptionError("receipt_drift")


def require_production_evidence(directory: Path, *, checkout_roots: tuple[Path, ...]) -> None:
    """Check location against roots whose identity the runtime adapter verified.

    Filesystem privacy/no-follow checks remain in read_private/write_private.
    Root provenance is supplied by RuntimeVerifier, not inferred from .git.
    """
    if (
        os.name != "posix"
        or not isinstance(directory, Path)
        or not directory.is_absolute()
        or not isinstance(checkout_roots, tuple)
        or not checkout_roots
    ):
        raise AdoptionError("production_evidence_location")
    try:
        evidence = directory.resolve(strict=False)
        if evidence != directory:
            raise AdoptionError("production_evidence_location")
        for root in checkout_roots:
            if (
                not isinstance(root, Path)
                or not root.is_absolute()
                or not root.is_dir()
                or root.resolve(strict=True) != root
                or evidence.is_relative_to(root)
            ):
                raise AdoptionError("production_evidence_location")
    except (OSError, RuntimeError, ValueError):
        raise AdoptionError("production_evidence_location") from None
