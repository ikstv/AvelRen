"""Синтетичні Git-тести без GitHub, production і реальних секретів."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "consolidate_legacy_repositories.py"
spec = importlib.util.spec_from_file_location("consolidation", MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.make_repo("target", "current ORIGINAL", extra={"services/live.py": "active = True\n"})
        self.a = self.make_repo("a", "legacy A", extra={"run.sh": "#!/bin/sh\necho legacy\n", "image.bin": b"\x00\x01\xff"})
        self.b = self.make_repo("b", "legacy ops", extra={".github/workflows/legacy.yml": "name: legacy\n"})
        self.expected = {"AvelRen": m.sha(self.a, "main"), "AvelRen-ops": m.sha(self.b, "main")}
        self.base = m.sha(self.target, "main")
        self.scanner = mock.Mock()

    def tearDown(self):
        # Windows може коротко утримувати щойно створені Git-файли.
        # Повтор лише для власного TemporaryDirectory; остаточна помилка видима.
        for attempt in range(5):
            try:
                self.temp.cleanup()
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def make_repo(self, name, text, extra=None):
        work = self.root / name
        m.git(None, "init", "--initial-branch=main", str(work))
        for path, content in {"README.md": text, **(extra or {})}.items():
            file = work / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(content if isinstance(content, bytes) else content.encode())
        m.git(work, "add", ".")
        m.git(work, "commit", "-m", "початковий стан")
        # Незлита гілка, анотований тег та PR ref повинні пережити bundle round trip.
        m.git(work, "checkout", "-b", "feature/unmerged")
        (work / "branch-only.txt").write_text("unmerged content", encoding="utf-8")
        m.git(work, "add", ".")
        m.git(work, "commit", "-m", "окрема гілка")
        m.git(work, "tag", "-a", "v-test", "-m", "annotated tag")
        m.git(work, "update-ref", "refs/pull/7/head", m.sha(work, "HEAD"))
        m.git(work, "checkout", "main")
        bare = self.root / (name + ".git")
        m.git(None, "clone", "--mirror", "--no-hardlinks", str(work), str(bare))
        return bare

    def prepare(self, **kwargs):
        args = dict(target=self.target, sources={"AvelRen": self.a, "AvelRen-ops": self.b},
                    output=self.root / "out", expected=self.expected,
                    expected_target=self.base, scanner=self.scanner)
        args.update(kwargs)
        return m.prepare(**args)

    def test_snapshots_bundles_parents_and_current_tree_are_preserved(self):
        before = {p: m.refs(p) for p in (self.target, self.a, self.b)}
        receipt = self.prepare()
        candidate = self.root / "out/candidate.git"
        commit = receipt["commit"]
        self.assertEqual(m.sha(candidate, f"{commit}:README.md"), m.sha(self.target, "main:README.md"))
        self.assertEqual(m.sha(candidate, f"{commit}:services"), m.sha(self.target, "main:services"))
        self.assertEqual(m.sha(candidate, "main"), self.base)
        parent_line = m.git(candidate, "rev-list", "--parents", "-n", "1", commit).decode().split()
        self.assertEqual(parent_line[1:], [self.base, self.expected["AvelRen"], self.expected["AvelRen-ops"]])
        self.assertEqual(m.git(candidate, "remote").strip(), b"")
        for name, source in (("AvelRen", self.a), ("AvelRen-ops", self.b)):
            info = receipt["manifest"]["sources"][name]
            self.assertEqual(m.sha(candidate, f"{commit}:{info['snapshot']}"), m.sha(source, "main^{tree}"))
            archived = m.git(candidate, "cat-file", "blob", f"{commit}:{info['bundle']}")
            original = (self.root / "out" / f"{name}.bundle").read_bytes()
            self.assertEqual(archived, original)
            restored = self.root / (name + "-restored.git")
            m.git(None, "clone", "--mirror", str(self.root / "out" / f"{name}.bundle"), str(restored))
            self.assertEqual(m.refs(restored), m.refs(source))
            for ref, oid in m.refs(source).items():
                self.assertEqual(m.git(restored, "cat-file", "-p", oid), m.git(source, "cat-file", "-p", oid), ref)
        self.assertEqual(before, {p: m.refs(p) for p in before})
        self.assertFalse(receipt["github_push_performed"])
        self.assertEqual(self.scanner.call_count, 4)
        self.assertEqual(json.loads((self.root / "out/RECEIPT.json").read_text())["commit"], commit)

    def test_source_sha_mismatch_stops_before_output(self):
        with self.assertRaises(m.MigrationError):
            self.prepare(expected={"AvelRen": "0" * 40, "AvelRen-ops": self.expected["AvelRen-ops"]})
        self.assertFalse((self.root / "out").exists())

    def test_target_sha_mismatch_stops_before_output(self):
        with self.assertRaises(m.MigrationError):
            self.prepare(expected_target="0" * 40)
        self.assertFalse((self.root / "out").exists())

    def test_existing_output_is_not_deleted(self):
        output = self.root / "out"
        output.mkdir()
        (output / "keep").write_text("keep")
        with self.assertRaises(m.MigrationError):
            self.prepare()
        self.assertEqual((output / "keep").read_text(), "keep")

    def test_scanner_failure_creates_no_candidate(self):
        with self.assertRaises(m.MigrationError):
            self.prepare(scanner=mock.Mock(side_effect=m.MigrationError("scan blocked")))
        self.assertFalse((self.root / "out/candidate.git").exists())
        self.assertFalse((self.root / "out/RECEIPT.json").exists())

    def test_current_worktree_is_rejected(self):
        with self.assertRaises(m.MigrationError):
            self.prepare(target=self.root / "target")

    def test_same_repo_cannot_be_both_sources(self):
        with self.assertRaises(m.MigrationError):
            self.prepare(sources={"AvelRen": self.a, "AvelRen-ops": self.a})

    def test_reserved_archive_cannot_be_overwritten(self):
        work = self.root / "target"
        (work / m.ARCHIVE).mkdir()
        (work / m.ARCHIVE / "keep").write_text("keep")
        m.git(work, "add", ".")
        m.git(work, "commit", "-m", "existing archive")
        m.git(self.target, "fetch", str(work), "main:main")
        with self.assertRaises(m.MigrationError):
            self.prepare(expected_target=m.sha(self.target, "main"))

    def test_lfs_pointer_is_blocked(self):
        work = self.root / "a"
        (work / "large.bin").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:" + "0" * 64 + "\nsize 10\n")
        m.git(work, "add", ".")
        m.git(work, "commit", "-m", "lfs pointer")
        m.git(self.a, "fetch", str(work), "main:main")
        expected = {**self.expected, "AvelRen": m.sha(self.a, "main")}
        with self.assertRaisesRegex(m.MigrationError, "LFS"):
            self.prepare(expected=expected)

    def test_crlf_lfs_pointer_is_blocked(self):
        work = self.root / "a"
        (work / "large.bin").write_bytes(
            b"version https://git-lfs.github.com/spec/v1\r\noid sha256:"
            + b"0" * 64 + b"\r\nsize 10\r\n"
        )
        m.git(work, "add", ".")
        m.git(work, "commit", "-m", "LFS із CRLF")
        m.git(self.a, "fetch", str(work), "main:main")
        expected = {**self.expected, "AvelRen": m.sha(self.a, "main")}
        with self.assertRaisesRegex(m.MigrationError, "LFS"):
            self.prepare(expected=expected)

    def test_bundle_limit_is_enforced(self):
        with mock.patch.object(m, "MAX_BUNDLE_BYTES", 1):
            with self.assertRaisesRegex(m.MigrationError, "80 MiB"):
                self.prepare()
        self.assertFalse((self.root / "out/RECEIPT.json").exists())

    def test_missing_gitleaks_is_not_silently_skipped(self):
        with mock.patch.object(m.shutil, "which", return_value=None):
            with self.assertRaisesRegex(m.MigrationError, "gitleaks"):
                m.scan_secrets(self.a, self.root)

    def test_target_history_scan_failure_creates_no_candidate(self):
        def scanner(repo, output):
            if repo == self.target:
                raise m.MigrationError("target scan blocked")
        with self.assertRaisesRegex(m.MigrationError, "target scan"):
            self.prepare(scanner=scanner)
        self.assertFalse((self.root / "out/candidate.git").exists())

    def test_final_candidate_scan_failure_creates_no_receipt(self):
        def scanner(repo, output):
            if repo.name == "candidate.git":
                raise m.MigrationError("candidate scan blocked")
        with self.assertRaisesRegex(m.MigrationError, "candidate scan"):
            self.prepare(scanner=scanner)
        self.assertFalse((self.root / "out/RECEIPT.json").exists())

    def test_source_movement_before_finalization_is_rejected(self):
        original_refs = m.refs
        seen = 0
        def moving_refs(repo):
            nonlocal seen
            result = original_refs(repo)
            if repo == self.a:
                seen += 1
                if seen >= 3:
                    return {**result, "refs/heads/concurrent": self.expected["AvelRen"]}
            return result
        with mock.patch.object(m, "refs", side_effect=moving_refs):
            with self.assertRaisesRegex(m.MigrationError, "змінилося"):
                self.prepare()
        self.assertFalse((self.root / "out/RECEIPT.json").exists())


if __name__ == "__main__":
    unittest.main()
