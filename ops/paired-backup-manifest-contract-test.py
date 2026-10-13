#!/usr/bin/env python3
"""Контракт completion record; лише синтетичні локальні artifacts."""

import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import paired_backup_manifest as manifest


class ManifestContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def pair(self, backup_id="20261013-010000"):
        artifacts = {}
        for key, suffix, content in [
            ("sql", ".sql.gz", b"SELECT 1;\n"),
            ("spool", ".spool.sqlite3.gz", b"SQLite fixture"),
        ]:
            name = f"avelren-{backup_id}{suffix}"
            data = gzip.compress(content)
            artifacts[key] = {
                "name": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
            (self.directory / name).write_bytes(data)
            (self.directory / f"{name}.sha256").write_text(f"{artifacts[key]['sha256']}  {name}\n")
        times = {
            "sql": {"started_at": "2026-10-13T01:00:00Z", "finished_at": "2026-10-13T01:01:00Z"},
            "spool": {"started_at": "2026-10-13T01:01:00Z", "finished_at": "2026-10-13T01:02:00Z"},
        }
        runtime = {
            "source_commit": "a" * 40,
            "image_id": "sha256:" + "b" * 64,
            "container_id": "c" * 64,
            "restart_count": 0,
            "started_at": "2026-10-12T00:00:00Z",
        }
        spool = {
            "schema_version": 1,
            "payload_version": 1,
            "state_counts": {"started": 1, "pending": 5, "acked": 3},
            "payload_count": 8,
            "cycle_range": {
                "first_seq": 1,
                "last_seq": 9,
                "first_at": "2026-10-12T00:00:00Z",
                "last_at": "2026-10-13T01:01:00Z",
            },
            "sha256": hashlib.sha256(b"SQLite fixture").hexdigest(),
            "bytes": 14,
        }
        return manifest.build_manifest(backup_id, artifacts, times, runtime, spool, True)

    def test_exact_same_id_pair(self):
        value = self.pair()
        self.assertEqual(value["format_version"], 1)
        self.assertEqual(value["backup_id"], "20261013-010000")
        self.assertEqual(value["tier"], "daily")
        self.assertEqual(manifest.validate_manifest(value), value)
        self.assertEqual(manifest.verify_local_pair(value, self.directory), value)
        self.assertEqual(self.pair("20261101-010000")["tier"], "monthly")
        self.assertEqual(self.pair("20261011-010000")["tier"], "weekly")

    def test_missing_writer_ack_rejected(self):
        value = self.pair()
        for flag in [False, None, 1, "true"]:
            changed = copy.deepcopy(value)
            changed["writer_resumed"] = flag
            with self.assertRaises(ValueError):
                manifest.validate_manifest(changed)

    def test_duplicate_keys_unknown_version_and_path_escape_rejected(self):
        value = self.pair()
        with self.assertRaises(ValueError):
            manifest.load_manifest('{"format_version":1,"format_version":1}')
        with self.assertRaises(ValueError):
            manifest.load_manifest(
                json.dumps(value).replace(
                    '"restart_count": 0', '"restart_count": 0, "restart_count": 0'
                )
            )
        for version in [2, True, "1"]:
            changed = copy.deepcopy(value)
            changed["format_version"] = version
            with self.assertRaises(ValueError):
                manifest.validate_manifest(changed)
        for name in ["../secret", "/tmp/secret", "C:\\secret", "nested/file", "nested\\file"]:
            changed = copy.deepcopy(value)
            changed["artifacts"]["sql"]["name"] = name
            with self.assertRaises(ValueError):
                manifest.validate_manifest(changed)
        value["runtime"]["credentials"] = "private"
        with self.assertRaises(ValueError):
            manifest.validate_manifest(value)

    def test_mixed_ids_and_bad_hash_rejected(self):
        value = self.pair()
        for name, digest in [
            ("avelren-20261012-010000.sql.gz", "e" * 64),
            (value["artifacts"]["sql"]["name"], "E" * 64),
        ]:
            changed = copy.deepcopy(value)
            changed["artifacts"]["sql"].update(name=name, sha256=digest)
            with self.assertRaises(ValueError):
                manifest.validate_manifest(changed)

    def test_partial_pair_rejected(self):
        value = self.pair()
        artifact = value["artifacts"]["spool"]["name"]
        sidecar = self.directory / f"{artifact}.sha256"
        sidecar.unlink()
        with self.assertRaises(ValueError):
            manifest.verify_local_pair(value, self.directory)
        sidecar.write_text("0" * 64 + f"  {artifact}\n")
        with self.assertRaises(ValueError):
            manifest.verify_local_pair(value, self.directory)
        sidecar.write_text(value["artifacts"]["spool"]["sha256"] + f"  {artifact}\n")
        (self.directory / artifact).write_bytes(b"truncated")
        with self.assertRaises(ValueError):
            manifest.verify_local_pair(value, self.directory)

    def test_retention_only_complete_paired_groups(self):
        for tier, keep, dates in [
            ("daily", 7, [f"202610{day:02}-010000" for day in [2, 3, 5, 6, 7, 8, 9, 10, 12]]),
            (
                "weekly",
                4,
                [
                    f"{date}-010000"
                    for date in [
                        "20260823",
                        "20260830",
                        "20260906",
                        "20260913",
                        "20260920",
                        "20260927",
                    ]
                ],
            ),
            ("monthly", 3, [f"2026{month:02}01-010000" for month in range(5, 10)]),
        ]:
            values = [self.pair(date) for date in dates]
            incomplete = copy.deepcopy(values[0])
            incomplete["writer_resumed"] = False
            candidates = manifest.retention_candidates(
                values + [incomplete, {"legacy_sql": "old.sql.gz"}], tier, keep
            )
            self.assertEqual(candidates, dates[:-keep])
            self.assertNotIn(dates[-1], candidates)

    def test_numeric_types_ranges_and_snapshot_order(self):
        value = self.pair()
        for path, invalid in [
            (("runtime", "restart_count"), True),
            (("artifacts", "sql", "bytes"), True),
            (("spool", "schema_version"), True),
            (("spool", "payload_count"), 99),
            (("spool", "cycle_range", "last_seq"), 0),
            (("snapshots", "sql", "finished_at"), "2026-10-13T00:00:00Z"),
            (("snapshots", "spool", "started_at"), "2026-10-13T00:00:00Z"),
            (("runtime", "started_at"), "2026-10-12T00:00:00"),
        ]:
            changed = copy.deepcopy(value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = invalid
            with self.assertRaises(ValueError):
                manifest.validate_manifest(changed)

    def test_gzip_invalid_even_with_matching_compressed_hash(self):
        value = self.pair()
        artifact = value["artifacts"]["sql"]
        data = b"this is not gzip"
        artifact.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        (self.directory / artifact["name"]).write_bytes(data)
        (self.directory / (artifact["name"] + ".sha256")).write_text(
            f"{artifact['sha256']}  {artifact['name']}\n"
        )
        with self.assertRaises(ValueError):
            manifest.verify_local_pair(value, self.directory)

    def test_uncompressed_spool_summary_matches_artifact(self):
        value = self.pair()
        for field, invalid in [("sha256", "f" * 64), ("bytes", 999)]:
            changed = copy.deepcopy(value)
            changed["spool"][field] = invalid
            with self.assertRaises(ValueError):
                manifest.verify_local_pair(changed, self.directory)

    def test_invalid_deflate_is_categorical(self):
        value = self.pair()
        artifact = value["artifacts"]["sql"]
        original = (self.directory / artifact["name"]).read_bytes()
        data = original[:10] + b"\x07" + original[-8:]
        artifact.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        (self.directory / artifact["name"]).write_bytes(data)
        (self.directory / (artifact["name"] + ".sha256")).write_text(
            f"{artifact['sha256']}  {artifact['name']}\n"
        )
        with self.assertRaises(manifest.ManifestError):
            manifest.verify_local_pair(value, self.directory)


if __name__ == "__main__":
    unittest.main()
