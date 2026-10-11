"""Strict, connection-local identity evidence for production adoption."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass

import psycopg
from psycopg.rows import tuple_row

from .adoption_inventory import AdoptionError


@dataclass(frozen=True)
class TargetBinding:
    format_version: int
    system_identifier: str
    database: str
    database_oid: int
    session_role: str
    source_commit: str
    runtime_digest: str


def _validate(binding: TargetBinding) -> None:
    if (
        type(binding.format_version) is not int
        or binding.format_version != 1
        or type(binding.database_oid) is not int
        or binding.database_oid <= 0
        or not isinstance(binding.system_identifier, str)
        or re.fullmatch(r"[1-9][0-9]*", binding.system_identifier) is None
        or any(
            not isinstance(value, str) or not value or "\x00" in value
            for value in (binding.database, binding.session_role)
        )
        or not isinstance(binding.source_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", binding.source_commit) is None
        or not isinstance(binding.runtime_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", binding.runtime_digest) is None
    ):
        raise AdoptionError("invalid_target_format")


def encode_target(binding: TargetBinding) -> bytes:
    _validate(binding)
    try:
        return json.dumps(
            asdict(binding), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeError:
        raise AdoptionError("invalid_target_format") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AdoptionError("invalid_target_format")
        result[key] = value
    return result


def decode_target(payload: bytes) -> TargetBinding:
    try:
        data = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != set(TargetBinding.__dataclass_fields__):
            raise AdoptionError("invalid_target_format")
        binding = TargetBinding(**data)
        encode_target(binding)
        return binding
    except (ValueError, TypeError, UnicodeError):
        raise AdoptionError("invalid_target_format") from None


def target_digest(binding: TargetBinding) -> str:
    return hashlib.sha256(encode_target(binding)).hexdigest()


def capture_target(conn, *, source_commit: str, runtime_digest: str) -> TargetBinding:
    try:
        with conn.cursor(row_factory=tuple_row) as cursor:
            cursor.execute(
                "SELECT c.system_identifier::text, d.datname, d.oid, session_user "
                "FROM pg_catalog.pg_control_system() AS c CROSS JOIN pg_catalog.pg_database AS d "
                "WHERE d.datname = pg_catalog.current_database()"
            )
            identity = cursor.fetchone()
    except psycopg.Error:
        raise AdoptionError("target_identity_read_failed") from None
    if identity is None:
        raise AdoptionError("target_identity_read_failed")
    binding = TargetBinding(1, *identity, source_commit, runtime_digest)
    _validate(binding)
    return binding


def verify_target(conn, expected: TargetBinding) -> None:
    _validate(expected)
    actual = capture_target(
        conn, source_commit=expected.source_commit, runtime_digest=expected.runtime_digest
    )
    if actual != expected:
        raise AdoptionError("target_mismatch")
