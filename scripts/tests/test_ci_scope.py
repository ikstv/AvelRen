import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_scope import classify


class ScopeTests(unittest.TestCase):
    def test_android_only(self):
        self.assertEqual(classify(["android/app/src/main/Example.kt"]), (False, True))

    def test_backend_only(self):
        self.assertEqual(classify(["app/src/avelren/api.py", "db/migrations/011.sql"]), (True, False))

    def test_documentation_only(self):
        self.assertEqual(classify(["docs/admin.md", "README.md"]), (False, False))

    def test_unknown_shared_and_ci_are_conservative(self):
        for path in ("new-component/file", "scripts/backend-test.sh", ".github/workflows/ci.yml"):
            self.assertEqual(classify([path]), (True, True))

    def test_mixed_changes(self):
        self.assertEqual(classify(["app/src/api.py", "android/gradle.lockfile"]), (True, True))

    def test_empty(self):
        self.assertEqual(classify([]), (False, False))
