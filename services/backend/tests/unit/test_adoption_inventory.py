"""Канонічний inventory без фізичних OID і витоку даних."""

import copy

import pytest

from avelren.adoption_inventory import (
    SECTIONS,
    AdoptionError,
    Snapshot,
    decode,
    encode,
    fingerprint,
)


def snapshot():
    sections = {name: [] for name in SECTIONS}
    sections["relations"] = [
        {
            "identity": "public.devices",
            "owner": "avelren",
            "oid": 123,
            "acl": [
                {
                    "grantor": "avelren",
                    "grantee": "PUBLIC",
                    "privilege": "SELECT",
                    "grantable": False,
                }
            ],
        },
        {"identity": "public.alerts", "owner": "avelren", "oid": 456, "acl": []},
    ]
    return Snapshot(1, "avelren_case_" + "a" * 32 + "_test", sections)


def test_canonical_encoding_roundtrip_and_row_order():
    before = snapshot()
    changed = copy.deepcopy(before)
    changed.sections["relations"].reverse()
    changed.sections["relations"][0]["oid"] = 900
    assert fingerprint(before) == fingerprint(changed)
    assert encode(decode(encode(before))) == encode(before)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "avelren_migrator"),
        ("grantor", "avelren_admin"),
        ("grantable", True),
    ],
)
def test_fingerprint_preserves_owner_and_delegation(field, value):
    before = snapshot()
    changed = copy.deepcopy(before)
    row = changed.sections["relations"][0]
    (row if field == "owner" else row["acl"][0])[field] = value
    assert fingerprint(before) != fingerprint(changed)


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"null", b"not-json"])
def test_invalid_snapshot_refused(payload):
    with pytest.raises(AdoptionError):
        decode(payload)


def test_unknown_format_refused():
    before = snapshot()
    with pytest.raises(AdoptionError):
        decode(encode(before).replace(b'"format_version":1', b'"format_version":2'))
