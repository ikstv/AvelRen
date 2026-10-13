"""Focused interruption/cleanup and slow-backup acceptance regressions."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

PATH = Path(__file__).with_name("paired-backup-daemon-test.py")
spec = importlib.util.spec_from_file_location("driver", PATH)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
DOCKER = "--docker" in sys.argv
if DOCKER:
    sys.argv.remove("--docker")
IMAGE = (
    "timescale/timescaledb:2.30.1-pg16@sha256:"
    "f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9"
)


class BoundaryContracts(unittest.TestCase):
    def test_slow_backup_needs_a_new_completed_cycle_after_completion(self):
        value = dict(
            calls=[dict(monotonic=t) for t in (0, 60, 120)],
            status=dict(pending_count=0, acked_count=3),
        )
        self.assertFalse(driver.completed_cycle_after(value, 130))
        value["calls"].append(dict(monotonic=180))
        self.assertFalse(driver.completed_cycle_after(value, 130))
        value["status"]["acked_count"] = 4
        self.assertTrue(driver.completed_cycle_after(value, 130))

    def test_removal_failure_does_not_skip_later_owned_removals(self):
        events = []
        cleanup = driver.Cleanup(seconds=5)

        def fail():
            events.append("first")
            raise OSError("synthetic removal failure")

        cleanup.add("first", fail)
        cleanup.add("second", lambda: events.append("second"))
        self.assertEqual(cleanup.finish(), ["first:OSError"])
        self.assertEqual(events, ["first", "second"])

    def test_registration_precedes_partial_creation_failure(self):
        tracked = []

        def create():
            self.assertEqual(tracked, ["owned-collector"])
            raise ValueError("partial start")

        with self.assertRaises(ValueError):
            driver.registered_create(tracked, "owned-collector", create)
        self.assertEqual(tracked, ["owned-collector"])

    def test_real_term_and_hup_enter_cleanup_and_preserve_failure(self):
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "cleaned"
                ready = Path(directory) / "ready"
                code = (
                    "import importlib.util,time;from pathlib import Path;"
                    f"s=importlib.util.spec_from_file_location('d',{str(PATH)!r});"
                    "d=importlib.util.module_from_spec(s);s.loader.exec_module(d);"
                    "d.install_cancellation();"
                    f"Path({str(ready)!r}).touch();\n"
                    "try: time.sleep(30)\n"
                    "finally:\n"
                    " c=d.Cleanup(seconds=5)\n"
                    f" c.add('marker',lambda:Path({str(marker)!r}).touch())\n"
                    " c.finish()\n"
                )
                process = subprocess.Popen(
                    [sys.executable, "-c", code],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists())
                    os.kill(process.pid, signum)
                    self.assertNotEqual(process.wait(timeout=8), 0)
                    self.assertTrue(marker.exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()

    def test_cancel_waits_for_own_child_trap_before_parent_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready, marker = root / "ready", root / "child-cleaned"
            child = root / "child.py"
            child.write_text(
                "import signal,time\nfrom pathlib import Path\n"
                "def cancel(*args): raise KeyboardInterrupt()\n"
                "signal.signal(signal.SIGTERM,cancel)\n"
                f"Path({str(ready)!r}).touch()\ntry: time.sleep(30)\n"
                f"finally: Path({str(marker)!r}).touch()\n"
            )
            code = (
                "import importlib.util,sys;"
                f"s=importlib.util.spec_from_file_location('d',{str(PATH)!r});"
                "d=importlib.util.module_from_spec(s);s.loader.exec_module(d);"
                "d.install_cancellation();"
                f"d.command([sys.executable,{str(child)!r}],seconds=30)"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                driver.wait(ready.exists, 5)
                os.kill(process.pid, signal.SIGTERM)
                self.assertNotEqual(process.wait(timeout=10), 0)
                self.assertTrue(marker.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


@unittest.skipUnless(DOCKER, "explicit real Docker boundary rehearsal")
class DockerCleanupContracts(unittest.TestCase):
    def setUp(self):
        self.prefix = (
            "avelren-runtime-test-pair-" + str(time.time_ns() % 100000000) + "-" + str(os.getpid())
        )
        self.names = []
        self.root_context = tempfile.TemporaryDirectory()
        self.root = Path(self.root_context.name)
        driver.FAILURE_LOG = self.root / "first-failure.log"

    def tearDown(self):
        for name in self.names:
            subprocess.run(["docker", "rm", "-fv", name], capture_output=True, timeout=15)
        self.root_context.cleanup()

    def create(self, suffix):
        name = self.prefix + "-" + suffix
        self.names.append(name)
        driver.command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--label",
                "org.avelren.test.fixture=" + self.prefix,
                "--entrypoint",
                "sh",
                IMAGE,
                "-c",
                "sleep 300",
            ]
        )
        return name

    def absent(self, name):
        return not driver.command(
            ["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"]
        ).strip()

    def test_actual_term_cleans_owned_container(self):
        name = self.create("signal")
        ready, marker = self.root / "ready", self.root / "marker"
        code = (
            "import importlib.util,time;from pathlib import Path;"
            f"s=importlib.util.spec_from_file_location('d',{str(PATH)!r});"
            "d=importlib.util.module_from_spec(s);s.loader.exec_module(d);d.install_cancellation();"
            f"Path({str(ready)!r}).touch();\n"
            "try: time.sleep(30)\nfinally:\n c=d.Cleanup(seconds=10)\n"
            f" c.add('owned',lambda:c.remove('container',{name!r},"
            f"{{'org.avelren.test.fixture':{self.prefix!r}}}))\n"
            f" assert c.finish()==[]\n Path({str(marker)!r}).touch()\n"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            driver.wait(ready.exists, 5)
            os.kill(process.pid, signal.SIGTERM)
            self.assertNotEqual(process.wait(timeout=15), 0)
            self.assertTrue(marker.exists())
            self.assertTrue(self.absent(name))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_removal_failure_still_removes_other_real_owned_container(self):
        first, second = self.create("first"), self.create("second")
        cleanup = driver.Cleanup(seconds=15)
        cleanup.add("first", lambda: (_ for _ in ()).throw(OSError("injected removal failure")))
        cleanup.add(
            "second",
            lambda: cleanup.remove("container", second, {"org.avelren.test.fixture": self.prefix}),
        )
        self.assertEqual(cleanup.finish(), ["first:OSError"])
        self.assertFalse(self.absent(first))
        self.assertTrue(self.absent(second))

    def test_prestate_job_journal_removes_owned_and_preserves_foreign_runtime(self):
        Path("/evidence").mkdir(mode=0o700, exist_ok=True)
        identity = dict(
            container_id="a" * 64,
            image_id="sha256:" + "b" * 64,
            source_commit="c" * 40,
            restart_count=0,
            started_at="2026-10-13T00:00:00Z",
            volume=self.prefix + "-spool",
            network=self.prefix + "-network",
        )
        generation = str(uuid.uuid4())
        driver.register_job_owner(self.root, self.prefix, generation, identity)
        self.assertEqual(
            driver.read_private_json(self.root / "job-owners.json"),
            [dict(generation=generation, identity=identity)],
        )
        self.assertFalse((self.root / "state").exists())
        for field, foreign in (
            ("volume", "avelren_collector_spool_v1"),
            ("network", "avelren_default"),
        ):
            with self.assertRaisesRegex(ValueError, "invalid_job_identity"):
                driver.validate_job_owners(
                    [dict(generation=generation, identity=dict(identity, **{field: foreign}))],
                    self.prefix,
                )
        runtime_hash = driver.hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        owned, foreign = ("avelren-paired-" + generation + "-" + kind for kind in ("check", "sql"))
        later_generation = str(uuid.uuid4())
        later_owned = "avelren-paired-" + later_generation + "-sql"
        driver.register_job_owner(self.root, self.prefix, later_generation, identity)
        for name, digest, owner in (
            (owned, runtime_hash, generation),
            (foreign, "f" * 64, generation),
            (later_owned, runtime_hash, later_generation),
        ):
            self.names.append(name)
            driver.command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--label",
                    "org.avelren.backup.generation=" + owner,
                    "--label",
                    "org.avelren.backup.runtime=" + digest,
                    "--entrypoint",
                    "sh",
                    IMAGE,
                    "-c",
                    "sleep 300",
                ]
            )
        ledger = dict(
            format_version=1,
            fixture=self.prefix,
            containers=[],
            images=[],
            created_volume=False,
            created_network=False,
            sql_started=False,
        )
        result = driver.cleanup_fixture(
            self.root, self.prefix, ledger, first_failure="original_probe_failure"
        )
        self.assertEqual(result["errors"], ["job-sql:ValueError"])
        self.assertEqual(result["first_failure"], "original_probe_failure")
        self.assertTrue(self.absent(owned))
        self.assertTrue(self.absent(later_owned))
        self.assertFalse(self.absent(foreign))

    def test_invalid_job_journal_does_not_skip_owned_container_cleanup(self):
        Path("/evidence").mkdir(mode=0o700, exist_ok=True)
        api = self.create("api")
        path = self.root / "job-owners.json"
        path.write_text("not-json")
        path.chmod(0o600)
        ledger = dict(
            format_version=1,
            fixture=self.prefix,
            containers=[api],
            images=[],
            created_volume=False,
            created_network=False,
            sql_started=False,
        )
        result = driver.cleanup_fixture(
            self.root, self.prefix, ledger, first_failure="original_probe_failure"
        )
        self.assertEqual(len(result["errors"]), 3)
        self.assertTrue(all("JSONDecodeError" in error for error in result["errors"]))
        self.assertEqual(result["first_failure"], "original_probe_failure")
        self.assertTrue(self.absent(api))

    def test_nested_project_cleanup_fences_paths_images_and_foreign_project(self):
        Path("/evidence").mkdir(mode=0o700, exist_ok=True)
        directory = self.root / "avelren-paired-restore.ABC12345"
        directory.mkdir(mode=0o700)
        project = "avelren-paired-restore-1-2-" + str(time.time_ns() % 100000000)
        foreign_project = project + "9"
        image_id = json.loads(driver.command(["docker", "image", "inspect", IMAGE]))[0]["Id"]
        manifest = dict(
            format_version=1,
            project=project,
            compose_file=str(self.root / "source/ops/compose.paired-restore-test.yml"),
            working_dir=str(directory),
            env_file=str(directory / "compose.env"),
            app_image=image_id,
        )
        driver.write_private_json(directory / "project.json", manifest)
        own, foreign = self.prefix + "-nested", self.prefix + "-foreign"
        for name, target in ((own, project), (foreign, foreign_project)):
            self.names.append(name)
            driver.command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    "none",
                    "--label",
                    "com.docker.compose.project=" + target,
                    "--label",
                    "com.docker.compose.service=db",
                    "--label",
                    "com.docker.compose.project.config_files=" + manifest["compose_file"],
                    "--label",
                    "com.docker.compose.project.working_dir=" + manifest["working_dir"],
                    "--entrypoint",
                    "sh",
                    IMAGE,
                    "-c",
                    "sleep 300",
                ]
            )
        # Reject a same-project foreign path before any Docker mutation.
        bad = dict(manifest, compose_file="/foreign/compose.yml")
        driver.write_private_json(directory / "project.json", bad)
        with self.assertRaisesRegex(ValueError, "invalid_nested_restore_journal"):
            driver.cleanup_nested_restore(self.root, directory, driver.Cleanup(seconds=15))
        self.assertFalse(self.absent(own))
        driver.write_private_json(directory / "project.json", manifest)
        driver.cleanup_nested_restore(self.root, directory, driver.Cleanup(seconds=15))
        self.assertTrue(self.absent(own))
        self.assertFalse(self.absent(foreign))
        self.assertFalse(directory.exists())

    def test_actual_partial_compose_start_remains_registered_and_removed(self):
        collector, bad = self.prefix + "-collector", self.prefix + "-bad"
        self.names.extend([collector, bad])
        compose_file = self.root / "partial.yml"
        compose_file.write_text(
            json.dumps(
                dict(
                    services={
                        "collector": dict(
                            image=IMAGE,
                            container_name=collector,
                            entrypoint=["sh"],
                            command=["-c", "sleep 300"],
                            network_mode="none",
                        ),
                        "bad": dict(
                            image=IMAGE,
                            container_name=bad,
                            entrypoint=["/missing-fixture-entrypoint"],
                            network_mode="none",
                            depends_on=["collector"],
                        ),
                    }
                )
            )
        )
        argv = ["docker", "compose", "-p", self.prefix, "-f", str(compose_file)]
        tracked = []
        with self.assertRaises(AssertionError):
            driver.registered_create(
                tracked, collector, lambda: driver.command([*argv, "up", "-d", "--pull", "never"])
            )
        self.assertEqual(tracked, [collector])
        self.assertFalse(self.absent(collector))
        cleanup = driver.Cleanup(seconds=15)
        cleanup.add(
            "partial",
            lambda: cleanup.remove(
                "container", tracked[0], {"com.docker.compose.project": self.prefix}
            ),
        )
        self.assertEqual(cleanup.finish(), [])
        self.assertTrue(self.absent(collector))

    def test_independent_outer_ledger_cleanup_preserves_original_failure(self):
        current = subprocess.run(
            ["docker", "inspect", os.environ.get("HOSTNAME", ""), "--format", "{{.Image}}"],
            capture_output=True,
            text=True,
        )
        if current.returncode:
            self.skipTest("outer fallback executes inside the real controller fixture")
        controller = current.stdout.strip()
        api = self.create("api")
        volumes = [self.prefix + "-controller-data", self.prefix + "-spool"]
        network = self.prefix + "-network"
        copier = self.prefix + "-copy"
        self.names.append(copier)
        try:
            for volume in volumes:
                driver.command(
                    [
                        "docker",
                        "volume",
                        "create",
                        "--label",
                        "org.avelren.test.fixture=" + self.prefix,
                        volume,
                    ]
                )
            driver.command(
                [
                    "docker",
                    "network",
                    "create",
                    "--internal",
                    "--label",
                    "org.avelren.test.fixture=" + self.prefix,
                    network,
                ]
            )
            mount = driver.command(
                ["docker", "volume", "inspect", volumes[0], "--format", "{{.Mountpoint}}"]
            ).strip()
            ledger = dict(
                format_version=1,
                fixture=self.prefix,
                containers=[api],
                images=[],
                created_volume=True,
                created_network=True,
                sql_started=False,
            )
            original = dict(
                format_version=1,
                fixture=self.prefix,
                status="FAIL",
                errors=["injected:OSError"],
                first_failure="synthetic_original_failure",
            )
            seed = (
                "import json,os;from pathlib import Path;"
                f"p=Path({mount!r});p.chmod(0o700);os.umask(0o077);"
                "(p/'source').mkdir();"
                f"(p/'owned.json').write_text({json.dumps(ledger)!r});"
                f"(p/'cleanup.json').write_text({json.dumps(original)!r})"
            )
            driver.command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    volumes[0] + ":" + mount,
                    controller,
                    "python3",
                    "-c",
                    seed,
                ]
            )
            driver.command(
                [
                    "docker",
                    "create",
                    "--name",
                    copier,
                    "--network",
                    "none",
                    "-v",
                    volumes[0] + ":" + mount,
                    controller,
                    "true",
                ]
            )
            driver.command(["docker", "cp", "/work/ops", copier + ":" + mount + "/source/ops"])
            driver.command(["docker", "rm", copier])
            stdout = driver.command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "-v",
                    "/var/run/docker.sock:/var/run/docker.sock",
                    "-v",
                    volumes[0] + ":" + mount,
                    "--tmpfs",
                    "/evidence",
                    controller,
                    "python3",
                    mount + "/source/ops/paired-backup-daemon-test.py",
                    "--cleanup-only",
                    "--source-commit",
                    "a" * 40,
                    "--prefix",
                    self.prefix,
                    "--fixture",
                    mount,
                ]
            )
            receipt = json.loads(stdout)
            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["original_receipt"], original)
            self.assertTrue(self.absent(api))
            self.assertNotIn(
                volumes[1], driver.command(["docker", "volume", "ls", "-q"]).splitlines()
            )
            self.assertNotIn(
                network,
                driver.command(["docker", "network", "ls", "--format", "{{.Name}}"]).splitlines(),
            )
        finally:
            subprocess.run(["docker", "rm", "-fv", copier], capture_output=True, timeout=15)
            for volume in volumes:
                subprocess.run(["docker", "volume", "rm", volume], capture_output=True, timeout=15)
            subprocess.run(["docker", "network", "rm", network], capture_output=True, timeout=15)


if __name__ == "__main__":
    unittest.main()
