"""Target evidence rejects ambiguous identities and malformed JSON."""

import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, replace

import psycopg
import pytest

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_target import (
    TargetBinding,
    capture_target,
    decode_target,
    encode_target,
    target_digest,
    verify_target,
)

BINDING = TargetBinding(1, "123456789", "avelren", 16384, "avelren_admin", "a" * 40, "b" * 64)
CANONICAL = (
    b'{"database":"avelren","database_oid":16384,"format_version":1,'
    b'"runtime_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
    b'"session_role":"avelren_admin","source_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    b'"system_identifier":"123456789"}'
)


def test_adoption_target_canonical_roundtrip():
    assert encode_target(BINDING) == CANONICAL
    assert decode_target(CANONICAL) == BINDING
    assert target_digest(BINDING) == hashlib.sha256(CANONICAL).hexdigest()
    assert target_digest(decode_target(json.dumps(asdict(BINDING), indent=2).encode())) == (
        hashlib.sha256(CANONICAL).hexdigest()
    )
    with pytest.raises(FrozenInstanceError):
        BINDING.database_oid = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", True),
        ("format_version", 2),
        ("format_version", 1.0),
        ("database_oid", True),
        ("database_oid", 0),
        ("database_oid", -1),
        ("database_oid", "1"),
        ("system_identifier", "0"),
        ("system_identifier", "-1"),
        ("system_identifier", 123),
        ("system_identifier", "1.2"),
        ("system_identifier", "١"),
        ("database", ""),
        ("database", "db\x00"),
        ("database", 123),
        ("session_role", ""),
        ("session_role", "role\x00"),
        ("source_commit", "A" * 40),
        ("source_commit", "a" * 39),
        ("source_commit", "g" * 40),
        ("runtime_digest", "B" * 64),
        ("runtime_digest", "b" * 63),
        ("runtime_digest", "g" * 64),
    ],
)
def test_adoption_target_invalid_format(field, value):
    data = asdict(BINDING)
    data[field] = value
    with pytest.raises(AdoptionError):
        decode_target(json.dumps(data).encode())
    with pytest.raises(AdoptionError):
        encode_target(replace(BINDING, **{field: value}))


@pytest.mark.parametrize(
    "payload",
    [
        b"null",
        b"[]",
        b"{}",
        b"{",
        b"\xff",
        CANONICAL.replace(b'{"database":', b'{"extra":1,"database":'),
        CANONICAL.replace(b'{"database":', b'{"database":"other","database":'),
    ],
)
def test_adoption_target_rejects_invalid_json(payload):
    with pytest.raises(AdoptionError):
        decode_target(payload)


class UnreadableConnection:
    def cursor(self, **kwargs):
        raise psycopg.errors.InsufficientPrivilege("sensitive connection details")


def test_adoption_target_identity_failure_has_no_fallback_or_sensitive_error():
    with pytest.raises(AdoptionError) as failure:
        capture_target(UnreadableConnection(), source_commit="a" * 40, runtime_digest="b" * 64)
    assert str(failure.value) == "target_identity_read_failed"
    assert failure.value.__cause__ is None
    with pytest.raises(AdoptionError):
        verify_target(UnreadableConnection(), BINDING)
