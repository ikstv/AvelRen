"""Production evidence binds every receipt to one operation and exact hashes."""

import hashlib
import json
import os
import uuid
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from avelren.adoption_inventory import SECTIONS, AdoptionError, Snapshot
from avelren.adoption_operation import (
    OperationManifest,
    decode_operation,
    encode_operation,
    make_operation,
    read_operation,
    require_production_evidence,
    verify_receipt,
    write_operation,
    write_receipt,
)
from avelren.adoption_plan import AdoptionPlan
from avelren.adoption_target import TargetBinding

BINDING = TargetBinding(1, "123456789", "avelren", 16384, "avelren_admin", "a" * 40, "b" * 64)
MANIFEST = OperationManifest(1, "c" * 32, "d" * 64, "e" * 64, "f" * 64, "0" * 64)
PHASES = (
    "apply-intent",
    "committed",
    "accepted",
    "inverse-intent",
    "inverse-committed",
    "inverse-accepted",
)


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def test_adoption_operation_roundtrip_and_binding(tmp_path):
    before = Snapshot(1, "avelren", {name: [] for name in SECTIONS})
    expected = Snapshot(1, "avelren", {**before.sections, "shared": [{"kind": "changed"}]})
    plan = AdoptionPlan(1, before, expected, ("safe forward",), ("safe inverse",))
    operation = make_operation(BINDING, plan)
    assert uuid.UUID(hex=operation.operation_id).version == 4
    assert operation.target_digest == hashlib.sha256(canonical(asdict(BINDING))).hexdigest()
    snapshots = [
        {"format_version": 1, "database": "avelren", "sections": snapshot.sections}
        for snapshot in (before, expected)
    ]
    assert operation.before_fingerprint == hashlib.sha256(canonical(snapshots[0])).hexdigest()
    assert operation.expected_fingerprint == hashlib.sha256(canonical(snapshots[1])).hexdigest()
    assert (
        operation.plan_digest
        == hashlib.sha256(
            canonical(
                {
                    "format_version": 1,
                    "before": snapshots[0],
                    "expected": snapshots[1],
                    "forward": ["safe forward"],
                    "inverse": ["safe inverse"],
                }
            )
        ).hexdigest()
    )
    assert encode_operation(operation) == canonical(asdict(operation))
    assert decode_operation(encode_operation(operation)) == operation
    write_operation(tmp_path / "private", operation)
    assert read_operation(tmp_path / "private") == operation
    with pytest.raises(FrozenInstanceError):
        operation.operation_id = "1" * 32


@pytest.mark.parametrize("phase", PHASES)
def test_adoption_receipt_cross_operation_refused(tmp_path, phase):
    write_receipt(tmp_path, phase, MANIFEST, category=None)
    verify_receipt(tmp_path, phase, MANIFEST)
    with pytest.raises(AdoptionError):
        verify_receipt(tmp_path, phase, replace(MANIFEST, operation_id="1" * 32))
    record = json.loads((tmp_path / f"production-{phase}.json").read_bytes())
    assert record == {**asdict(MANIFEST), "phase": phase, "category": None}


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", True),
        ("format_version", 2),
        ("format_version", 1.0),
        ("operation_id", "c" * 31),
        ("operation_id", "C" * 32),
        ("operation_id", 1),
        ("target_digest", "d" * 63),
        ("plan_digest", "E" * 64),
        ("before_fingerprint", "g" * 64),
        ("expected_fingerprint", None),
    ],
)
def test_operation_invalid_field_refused(field, value):
    with pytest.raises(AdoptionError):
        encode_operation(replace(MANIFEST, **{field: value}))
    with pytest.raises(AdoptionError):
        decode_operation(canonical({**asdict(MANIFEST), field: value}))


@pytest.mark.parametrize(
    "payload",
    [
        b"null",
        b"[]",
        b"{}",
        b"{",
        b"\xff",
        canonical({**asdict(MANIFEST), "extra": 1}),
        canonical(asdict(MANIFEST)).replace(b"{", b'{"format_version":1,', 1),
    ],
)
def test_operation_ambiguous_json_refused(payload):
    with pytest.raises(AdoptionError):
        decode_operation(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"target_digest": "1" * 64},
        {"plan_digest": "1" * 64},
        {"before_fingerprint": "1" * 64},
        {"expected_fingerprint": "1" * 64},
        {"phase": "accepted"},
        {"extra": 1},
        {"format_version": True},
        {"category": "postgresql://secret:sentinel@host/db"},
    ],
)
def test_receipt_hash_and_fields_tampering_refused(tmp_path, change):
    write_receipt(tmp_path, "committed", MANIFEST, category=None)
    path = tmp_path / "production-committed.json"
    data = json.loads(path.read_bytes())
    path.write_bytes(canonical({**data, **change}))
    with pytest.raises(AdoptionError):
        verify_receipt(tmp_path, "committed", MANIFEST)


@pytest.mark.parametrize(
    "payload",
    [
        b"{",
        b"null",
        b'{"status":"adopted","database":"avelren","plan_sha256":"foreign"}',
        canonical({**asdict(MANIFEST), "phase": "committed", "category": None}).replace(
            b"{", b'{"phase":"committed",', 1
        ),
    ],
)
def test_receipt_corrupt_or_disposable_refused(tmp_path, payload):
    path = tmp_path / "production-committed.json"
    path.write_bytes(payload)
    path.chmod(0o600)
    with pytest.raises(AdoptionError):
        verify_receipt(tmp_path, "committed", MANIFEST)


def test_operation_and_receipts_never_overwrite(tmp_path):
    write_operation(tmp_path, MANIFEST)
    write_receipt(tmp_path, "committed", MANIFEST, category=None)
    with pytest.raises(AdoptionError):
        write_operation(tmp_path, replace(MANIFEST, operation_id="1" * 32))
    with pytest.raises(AdoptionError):
        write_receipt(tmp_path, "committed", MANIFEST, category=None)
    assert read_operation(tmp_path) == MANIFEST
    verify_receipt(tmp_path, "committed", MANIFEST)
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "production-operation.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("tamper", ["manifest", "checksum", "missing-checksum"])
def test_operation_checksum_tampering_refused(tmp_path, tamper):
    write_operation(tmp_path, MANIFEST)
    if tamper == "manifest":
        (tmp_path / "production-operation.json").write_bytes(
            encode_operation(replace(MANIFEST, target_digest="1" * 64))
        )
    elif tamper == "checksum":
        (tmp_path / "production-operation.sha256").write_bytes(b"0" * 64 + b"\n")
    else:
        (tmp_path / "production-operation.sha256").unlink()
    with pytest.raises(AdoptionError):
        read_operation(tmp_path)


def test_interrupted_operation_sidecar_refuses_resume(tmp_path, monkeypatch):
    real_link = os.link

    def interrupted(source, destination, **kwargs):
        if destination == "production-operation.sha256":
            raise OSError("sentinel-credential")
        real_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", interrupted)
    with pytest.raises(AdoptionError):
        write_operation(tmp_path, MANIFEST)
    with pytest.raises(AdoptionError):
        read_operation(tmp_path)
    with pytest.raises(AdoptionError):
        write_operation(tmp_path, MANIFEST)
    assert (tmp_path / "production-operation.json").read_bytes() == encode_operation(MANIFEST)


def test_foreign_checksum_is_preserved_after_publication_refusal(tmp_path):
    path = tmp_path / "production-operation.sha256"
    path.write_bytes(b"foreign-evidence")
    path.chmod(0o600)
    with pytest.raises(AdoptionError):
        write_operation(tmp_path, MANIFEST)
    assert path.read_bytes() == b"foreign-evidence"
    with pytest.raises(AdoptionError):
        read_operation(tmp_path)


@pytest.mark.parametrize("checksum", [b"0" * 64, b"G" * 64 + b"\n", b"0" * 64 + b"\n\n"])
def test_operation_checksum_encoding_is_strict(tmp_path, checksum):
    write_operation(tmp_path, MANIFEST)
    (tmp_path / "production-operation.sha256").write_bytes(checksum)
    with pytest.raises(AdoptionError):
        read_operation(tmp_path)


@pytest.mark.parametrize("category", ["acceptance_failed", "", "sentinel-credential", 1])
def test_receipt_success_phase_never_records_failure_category(tmp_path, category):
    with pytest.raises(AdoptionError):
        write_receipt(tmp_path, "accepted", MANIFEST, category=category)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase", ["", "unknown", "../accepted", "apply", "inverse"])
def test_unknown_receipt_phase_refused(tmp_path, phase):
    with pytest.raises(AdoptionError):
        write_receipt(tmp_path, phase, MANIFEST, category=None)
    with pytest.raises(AdoptionError):
        verify_receipt(tmp_path, phase, MANIFEST)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "kind", ["file-symlink", "directory-symlink", "hardlink", "public-file", "public-directory"]
)
def test_unsafe_evidence_refused(tmp_path, kind):
    directory = tmp_path / "private"
    write_operation(directory, MANIFEST)
    path = directory / "production-operation.json"
    if kind == "file-symlink":
        path.rename(directory / "saved")
        path.symlink_to(directory / "saved")
    elif kind == "directory-symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        directory = alias
    elif kind == "hardlink":
        os.link(path, directory / "alias")
    elif kind == "public-file":
        path.chmod(0o644)
    else:
        directory.chmod(0o755)
    with pytest.raises(AdoptionError):
        read_operation(directory)


@pytest.mark.parametrize("failure", ["write", "file-fsync", "directory-fsync", "link"])
def test_interrupted_production_publication_leaves_no_receipt(tmp_path, monkeypatch, failure):
    real_fsync = os.fsync
    count = 0

    def denied(*args, **kwargs):
        raise OSError("sentinel-secret-dsn")

    def interrupted(fd):
        nonlocal count
        count += 1
        if count == (1 if failure == "file-fsync" else 2):
            denied()
        real_fsync(fd)

    monkeypatch.setattr(
        os,
        "fsync" if failure.endswith("fsync") else failure,
        interrupted if failure.endswith("fsync") else denied,
    )
    with pytest.raises(AdoptionError) as caught:
        write_receipt(tmp_path, "committed", MANIFEST, category=None)
    assert "sentinel-secret-dsn" not in str(caught.value)
    assert list(tmp_path.iterdir()) == []


def test_production_evidence_absolute_outside_verified_checkout(tmp_path):
    checkout = Path(__file__).resolve().parents[4]
    require_production_evidence(tmp_path, checkout_roots=(checkout,))
    with pytest.raises(AdoptionError):
        require_production_evidence(Path("relative"), checkout_roots=(checkout,))
    with pytest.raises(AdoptionError):
        require_production_evidence(checkout / "private", checkout_roots=(checkout,))
    with pytest.raises(AdoptionError):
        require_production_evidence(checkout, checkout_roots=(checkout,))
    with pytest.raises(AdoptionError):
        require_production_evidence(tmp_path, checkout_roots=())
    with pytest.raises(AdoptionError):
        require_production_evidence(tmp_path, checkout_roots=(tmp_path / "unknown",))


def test_production_evidence_checks_all_roots_and_aliases(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir(mode=0o700)
    private = root / "private"
    private.mkdir(mode=0o700)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    with pytest.raises(AdoptionError):
        require_production_evidence(private, checkout_roots=(other, root))
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(AdoptionError):
        require_production_evidence(other, checkout_roots=(alias,))
    with pytest.raises(AdoptionError):
        require_production_evidence(alias / "private", checkout_roots=(root,))
    with pytest.raises(AdoptionError):
        require_production_evidence(other, checkout_roots=(Path("relative"),))
