"""Контракт окремого runtime; Compose config не запускає daemon."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "ops/collector-runtime-preflight.py"


def load_module():
    spec = importlib.util.spec_from_file_location("runtime_preflight", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeContract(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env = self.root / "collector.env"
        self.env.write_text(
            "DATABASE_URL=sentinel-$PASSWORD 'quoted'\nECHERHA_DEVICE_ID=11111111-1111-4111-8111-111111111111\n"
        )
        self.env.chmod(0o600)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.manifest = {
            "source_commit": "a" * 40,
            "image_id": "sha256:" + "b" * 64,
            "env_file": str(self.env.resolve()),
            "compose_file": str((ROOT / "ops/compose.collector-runtime.yml").resolve()),
            "project": "avelren-runtime-test-unit",
            "container_name": "avelren-runtime-test-unit-collector",
            "network": "avelren-runtime-test-unit-network",
            "volume": "avelren-runtime-test-unit-volume",
            "state_dir": str(self.state.resolve()),
        }
        self.path = self.root / "manifest.json"

    def save(self):
        self.path.write_text(json.dumps(self.manifest))
        self.path.chmod(0o600)

    def config(self, resolve=True):
        env = dict(
            os.environ,
            COLLECTOR_IMAGE_ID=self.manifest["image_id"],
            COLLECTOR_ENV_FILE=self.manifest["env_file"],
            COLLECTOR_CONTAINER_NAME=self.manifest["container_name"],
            COLLECTOR_NETWORK=self.manifest["network"],
            COLLECTOR_VOLUME=self.manifest["volume"],
        )
        args = [
            "docker",
            "compose",
            "-p",
            self.manifest["project"],
            "-f",
            self.manifest["compose_file"],
            "config",
            "--format",
            "json",
        ]
        if not resolve:
            args.append("--no-env-resolution")
        p = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(p.returncode, 0, "Compose config failed (output withheld)")
        return json.loads(p.stdout)

    def test_single_service_external_resources(self):
        cfg = self.config(resolve=False)
        self.assertEqual(set(cfg["services"]), {"collector"})
        svc = cfg["services"]["collector"]
        for key in ("build", "depends_on", "ports", "mem_limit", "cpus"):
            self.assertNotIn(key, svc)
        self.assertEqual(svc["image"], self.manifest["image_id"])
        self.assertEqual(
            cfg["volumes"]["collector_spool"],
            {"name": self.manifest["volume"], "external": True},
        )
        self.assertEqual(cfg["networks"]["runtime"]["name"], self.manifest["network"])
        self.assertTrue(cfg["networks"]["runtime"]["external"])

    def test_security_matches_live(self):
        svc = self.config()["services"]["collector"]
        self.assertEqual(svc["user"], "10001:10001")
        self.assertTrue(svc["read_only"])
        self.assertEqual(svc["cap_drop"], ["ALL"])
        self.assertEqual(svc["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(svc["pids_limit"], 128)
        self.assertEqual(svc["restart"], "unless-stopped")
        self.assertIn("size=64m", svc["tmpfs"][0])

    def test_env_values_are_literal(self):
        # Canonical Compose config escapes literal dollars for serialization.
        self.assertEqual(
            self.config()["services"]["collector"]["environment"]["DATABASE_URL"],
            "sentinel-$$PASSWORD 'quoted'",
        )

    def test_missing_manifest_field_denied(self):
        del self.manifest["image_id"]
        self.save()
        with self.assertRaises(ValueError):
            load_module().load_manifest(self.path, test_mode=True)

    def test_private_file_permissions_denied(self):
        self.save()
        self.env.chmod(0o666)
        with self.assertRaises(ValueError):
            load_module().load_manifest(self.path, test_mode=True)

    def runtime(self):
        cfg = self.config(resolve=False)
        item = {
            "Id": "c" * 64,
            "Name": "/" + self.manifest["container_name"],
            "Image": self.manifest["image_id"],
            "State": {"Running": True, "Restarting": False, "Dead": False},
            "RestartCount": 0,
            "Config": {
                "Cmd": ["python", "-m", "avelren.collector"],
                "User": "10001:10001",
                "Env": ["AVELREN_GIT_SHA=" + self.manifest["source_commit"]],
                "Labels": {
                    "com.docker.compose.project": self.manifest["project"],
                    "com.docker.compose.service": "collector",
                },
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": self.manifest["volume"],
                    "Destination": "/var/lib/avelren/collector-spool",
                    "RW": True,
                }
            ],
            "NetworkSettings": {"Networks": {self.manifest["network"]: {}}},
            "HostConfig": {
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 128,
                "RestartPolicy": {"Name": "unless-stopped"},
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=64m"},
            },
        }
        return cfg, item

    def verdict(self, cfg, items):
        return load_module().validate_runtime(
            self.manifest, cfg, items, require_managed=True
        )

    def test_stopped_legacy_preserved(self):
        cfg, item = self.runtime()
        legacy = deepcopy(item)
        legacy.update(Name="/avelren-collector-rollback-a28360af", Id="d" * 64)
        legacy["State"]["Running"] = False
        legacy["Config"]["Labels"]["com.docker.compose.project"] = "avelren"
        self.assertEqual(self.verdict(cfg, [item, legacy]), [])

    def test_duplicate_stopped_managed_service_denied(self):
        cfg, item = self.runtime()
        item["State"]["Running"] = False
        other = deepcopy(item)
        other.update(Name="/renamed-managed-rollback", Id="d" * 64)
        self.assertIn("additional_managed_collector", self.verdict(cfg, [item, other]))

    def test_foreign_canonical_container_denied(self):
        cfg, item = self.runtime()
        item["Config"]["Labels"] = {}
        self.assertIn("unmanaged_target", self.verdict(cfg, [item]))

    def test_second_poller_custom_name_denied(self):
        cfg, item = self.runtime()
        other = deepcopy(item)
        other.update(Name="/arbitrary-other-poller", Id="d" * 64)
        other["Config"]["Labels"] = {}
        self.assertIn("additional_running_collector", self.verdict(cfg, [item, other]))

    def test_wrong_image_volume_network_denied(self):
        cfg, item = self.runtime()
        item["Image"] = "wrong"
        item["Mounts"][0]["Name"] = "wrong"
        item["NetworkSettings"]["Networks"] = {"wrong": {}}
        errors = self.verdict(cfg, [item])
        self.assertTrue({"wrong_image", "wrong_volume", "wrong_network"} <= set(errors))

    def test_image_source_sha_mismatch(self):
        cfg, item = self.runtime()
        item["Config"]["Env"] = ["AVELREN_GIT_SHA=wrong"]
        self.assertIn("wrong_source_commit", self.verdict(cfg, [item]))

    def test_missing_external_resource_denied(self):
        cfg, item = self.runtime()
        cfg["volumes"]["collector_spool"]["external"] = False
        self.assertIn("unsafe_compose_resources", self.verdict(cfg, [item]))

    def test_legacy_restore_topology(self):
        _, item = self.runtime()
        item["Name"] = "/avelren-collector-1"
        item["Config"]["Labels"]["com.docker.compose.project"] = "avelren"
        item["Mounts"] = []
        self.assertEqual(load_module().require_legacy_restore_topology([item]), [])

    def test_separate_restore_topology_denied(self):
        _, item = self.runtime()
        self.assertTrue(load_module().require_legacy_restore_topology([item]))

    def test_empty_restore_topology_denied(self):
        self.assertTrue(load_module().require_legacy_restore_topology([]))

    def test_unsafe_compose_env_file_denied(self):
        cfg, item = self.runtime()
        cfg["services"]["collector"]["env_file"] = [
            {"path": "/wrong/env", "format": "raw", "required": True}
        ]
        self.assertIn("unsafe_compose_env", self.verdict(cfg, [item]))

    def test_privileged_config_denied(self):
        cfg, item = self.runtime()
        cfg["services"]["collector"]["privileged"] = True
        self.assertIn("unsafe_compose_security", self.verdict(cfg, [item]))


if __name__ == "__main__":
    unittest.main()
