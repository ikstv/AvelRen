"""The internal fixture seam cannot select production/foreign SQL projects."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


class DisposableContract(unittest.TestCase):
    def test_validated_binding_and_production_default(self):
        spec = importlib.util.spec_from_file_location(
            "paired", Path(__file__).with_name("paired-backup.py")
        )
        paired = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(paired)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            env = root / "env"
            env.write_text("synthetic")
            env.chmod(0o600)
            manifest = dict(
                source_commit="a" * 40,
                image_id="sha256:" + "b" * 64,
                env_file=str(env),
                state_dir=str(root),
                compose_file=str(
                    Path(__file__).with_name("compose.collector-runtime.yml").resolve()
                ),
                project="avelren-runtime-test-unit",
                container_name="avelren-runtime-test-unit-collector",
                network="avelren-runtime-test-unit-network",
                volume="avelren-runtime-test-unit-volume",
            )
            path = root / "manifest"
            path.write_text(json.dumps(manifest))
            path.chmod(0o600)
            self.assertEqual(paired.Runtime(manifest, root)._sql_project, "avelren")
            for project in ("avelren", "foreign", "avelren-runtime-test-other-sql"):
                with self.assertRaisesRegex(ValueError, "disposable_sql_project_mismatch"):
                    paired.Runtime.for_disposable(path, root, root, sql_project=project)
            valid = paired.Runtime.for_disposable(
                path, root, root, sql_project=manifest["project"] + "-sql"
            )
            self.assertEqual(valid._sql_project, manifest["project"] + "-sql")
            manifest["project"] = "avelren"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "unsafe_test_resource"):
                paired.Runtime.for_disposable(path, root, root, sql_project="avelren-sql")


if __name__ == "__main__":
    unittest.main()
