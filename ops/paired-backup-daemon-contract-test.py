"""Focused interruption/cleanup and slow-backup acceptance regressions."""

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import paired_backup_state as state

PATH = Path(__file__).with_name("paired-backup-daemon-test.py")
spec = importlib.util.spec_from_file_location("driver", PATH)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
DOCKER = "--docker" in sys.argv
if DOCKER:
    sys.argv.remove("--docker")
LOCAL_BASE = "--local-base" in sys.argv
if LOCAL_BASE:
    sys.argv.remove("--local-base")
IMAGE = (
    "timescale/timescaledb:2.30.1-pg16@sha256:"
    "f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9"
)


class BoundaryContracts(unittest.TestCase):
    def test_slow_backup_needs_a_new_completed_cycle_after_completion(self):
        value = dict(
            calls=[dict(monotonic=t, native_attempt_monotonic=t) for t in (0, 60, 120)],
            status=dict(pending_count=0, acked_count=3),
        )
        self.assertFalse(driver.completed_cycle_after(value, 130))
        value["calls"].append(dict(monotonic=180, native_attempt_monotonic=180))
        self.assertFalse(driver.completed_cycle_after(value, 130))
        value["status"]["acked_count"] = 4
        self.assertTrue(driver.completed_cycle_after(value, 130))
        value["calls"][-1]["native_attempt_monotonic"] = 129
        self.assertFalse(driver.completed_cycle_after(value, 130))

    def test_native_request_starts_are_strict_despite_transport_dispatch_jitter(self):
        calls = [dict(native_attempt_monotonic=0.0, monotonic=.002),
                 dict(native_attempt_monotonic=60.001, monotonic=60.0015)]
        self.assertLess(calls[1]["monotonic"] - calls[0]["monotonic"], 60)
        self.assertEqual(driver.native_request_intervals(calls), [60.001])
        calls[1]["native_attempt_monotonic"] = 59.999
        with self.assertRaisesRegex(ValueError, "native_request_interval"):
            driver.native_request_intervals(calls)
        calls[1].pop("native_attempt_monotonic")
        with self.assertRaises((KeyError, ValueError)):
            driver.native_request_intervals(calls)

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
        self.assertEqual(len(result["errors"]), 5)
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


@unittest.skipUnless(DOCKER, "explicit real Docker control lifetime regression")
class DockerLifetimeContracts(unittest.TestCase):
    """Real daemon jobs/native mode writes; runtime identity is a local fixture.

    Full Compose identity/SQL/producer acceptance remains in the native rehearsal.
    No observer journal supplies recovery authority in these production-path probes.
    """

    @classmethod
    def setUpClass(cls):
        cls.build_context = tempfile.TemporaryDirectory(dir="/root")
        cls.build = Path(cls.build_context.name)
        cls.helper_tag = "avelren-runtime-test-life-helper-" + uuid.uuid4().hex[:12]
        cls.base_tag = cls.helper_tag + "-base"
        cls.addClassCleanup(cls.build_context.cleanup)
        try:
            source = subprocess.check_output(["git", "-C", str(PATH.parents[1]),
                                              "rev-parse", "HEAD"], text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            if not LOCAL_BASE:
                raise
            source = "8b2b38d105f5e891148dcf0364a201d7a9b01bf5"  # Local WIP fixture base.
        if LOCAL_BASE:
            subprocess.run(["docker", "tag", driver.APP, cls.base_tag], check=True,
                           capture_output=True, timeout=15)
            cls.addClassCleanup(lambda: subprocess.run(["docker", "image", "rm", cls.base_tag],
                                                       capture_output=True, timeout=20))
            shutil.copytree(PATH.parents[1] / "services/backend/src/avelren", cls.build / "avelren")
            (cls.build / "Dockerfile").write_text(
                f"FROM {cls.base_tag}\nUSER root\n"
                "COPY avelren /usr/local/lib/python3.14/site-packages/avelren\n"
                f"ENV AVELREN_GIT_SHA={source}\nUSER 10001:10001\n")
            build = ["--network", "none", "--pull=false", str(cls.build)]
        else:
            build = ["--build-arg", "SOURCE_COMMIT=" + source,
                     str(PATH.parents[1] / "services/backend")]
        result = subprocess.run(["docker", "build", "-t", cls.helper_tag, *build],
                                capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.addClassCleanup(lambda: subprocess.run(["docker", "image", "rm", cls.helper_tag],
                                                   capture_output=True, timeout=20))

    def setUp(self):
        self.paired = driver.load(PATH.with_name("paired-backup.py"), "lifetime_paired")
        self.context = tempfile.TemporaryDirectory(dir="/root")
        self.root = Path(self.context.name)
        self.work, self.directory = self.root / "work", self.root / "state"
        self.work.mkdir(mode=0o700)
        self.directory.mkdir(mode=0o700)
        self.prefix = "avelren-runtime-test-life-" + uuid.uuid4().hex[:12]
        self.volume = self.prefix + "-spool"
        self.names = []
        self.generations = []
        self.image = driver.command(["docker", "image", "inspect", self.helper_tag,
                                     "--format", "{{.Id}}"] ).strip()
        driver.FAILURE_LOG = self.root / "first-failure.log"
        info = json.loads(driver.command(["docker", "image", "inspect", self.image]))[0]
        source = next(e.split("=", 1)[1] for e in info["Config"]["Env"]
                      if e.startswith("AVELREN_GIT_SHA="))
        imported = driver.command([
            "docker", "run", "--rm", "--network", "none", self.image, "python", "-c",
            "import hashlib,json;import avelren.paired_backup_spool as p;"
            "import avelren.collector_control as c;"
            "print(json.dumps(dict(spool=p.__file__,control=c.__file__,"
            "sha=hashlib.sha256(open(p.__file__,'rb').read()).hexdigest())))",
        ])
        origin = json.loads(imported)
        self.assertIn("site-packages/avelren/collector_control.py", origin["control"])
        self.assertIn("site-packages/avelren/paired_backup_spool.py", origin["spool"])
        self.environment = patch.dict(os.environ, {
            "AVELREN_BACKUP_HELPER_IMAGE": self.image,
            "AVELREN_BACKUP_HELPER_SOURCE_COMMIT": source,
            "AVELREN_BACKUP_HELPER_SHA256": origin["sha"],
            "AVELREN_BACKUP_PASSWORD": "local-fixture-only",
            "DOCKER_HOST": "sentinel-invalid-host", "DOCKER_CONTEXT": "sentinel-context",
            "DOCKER_CONFIG": "/sentinel-config",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Driver's explicit environment keeps ambient sentinels out of Docker.
        self.docker_environment = self.paired.command_environment(docker=True)
        self.docker(["volume", "create", "--label", "org.avelren.test.fixture=" + self.prefix,
                     self.volume])
        self.addCleanup(self.cleanup)
        initialize = (
            "import os;from pathlib import Path;from avelren.collector_spool import SpoolStore;"
            f"p=Path({driver.SPOOL!r});os.chown(p,10001,10001);"
            "s=SpoolStore(p/'cycles.sqlite3');s.set_capture_only(False);s.set_mode_ack(False);"
            "s.close();[os.chown(f,10001,10001) for f in p.iterdir()]"
        )
        self.docker(["run", "--rm", "--network", "none", "--user", "0",
                     "-v", self.volume + ":" + driver.SPOOL, self.image,
                     "python", "-c", initialize])
        self.collector = self.prefix + "-writer"
        self.names.append(self.collector)
        ack = (
            "import time;from pathlib import Path;from avelren.collector_spool import SpoolStore;"
            f"s=SpoolStore(Path({driver.SPOOL!r})/'cycles.sqlite3');\n"
            "while True:\n s.set_mode_ack(s.status().capture_only);time.sleep(.05)\n"
        )
        collector_id = self.docker(["run", "-d", "--network", "none", "--name", self.collector,
                                   "--user", "10001:10001", "--label",
                                   "org.avelren.test.fixture=" + self.prefix, "-v",
                                   self.volume + ":" + driver.SPOOL, self.image,
                                   "python", "-c", ack]).strip()
        target = json.loads(self.docker(["inspect", collector_id]))[0]
        self.target = target
        self.identity = dict(container_id=collector_id, image_id=self.image, source_commit=source,
                             restart_count=0, started_at=target["State"]["StartedAt"],
                             volume=self.volume, network=self.prefix + "-network")
        self.manifest = dict(state_dir=str(self.directory), container_name=self.collector,
                             volume=self.volume, source_commit=source)

    def docker(self, argv):
        result = subprocess.run(["docker", *argv], env=self.docker_environment,
                                capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise AssertionError(result.stderr)
        return result.stdout

    def cleanup(self):
        for generation in self.generations:
            for kind in ("check", "sql", "spool", "control-on", "control-off"):
                name = "avelren-paired-" + generation + "-" + kind
                if self.docker(["ps", "-aq", "--filter", "name=^/" + name + "$"]).strip():
                    self.docker(["rm", "-f", name])
        for name in reversed(self.names):
            if self.docker(["ps", "-aq", "--filter", "name=^/" + name + "$"]).strip():
                self.docker(["rm", "-f", name])
        self.docker(["volume", "rm", self.volume])
        self.context.cleanup()

    def status(self):
        return json.loads(self.docker(["exec", self.collector, "python", "-m",
                                      "avelren.collector_control", "capture-only", "status"]))

    def runtime(self, *, delay=None, check=None):
        runtime = self.paired.Runtime(self.manifest, self.work)
        runtime.verify_client = lambda: None  # Client/plugin proof has the native rehearsal.
        runtime.identity = lambda: dict(self.identity)
        runtime.prepare_sql = lambda: None
        runtime.controller.runtime.preflight = lambda manifest, **kw: (manifest, self.target)
        runtime.controller.runtime.compose_command = lambda manifest: ([], {})
        native_job = runtime.job

        def job(kind, image, options, command, output):
            if kind == "control-on" and delay == "startup-on":
                # Two-second remaining budget exercises the remote lifetime
                # before costly native spool initialization, without extending it.
                gate = (
                    "import os,time\n"
                    f"fd=os.open({driver.SPOOL!r}+'/before-set',os.O_CREAT|os.O_WRONLY,0o600);"
                    "os.close(fd)\n"
                    f"while not os.path.exists({driver.SPOOL!r}+'/release'): time.sleep(.02)\n"
                )
                command = ["python", "-c", gate + command[-1]]
            elif kind == "control-" + str(delay):
                gate = (
                    "from pathlib import Path;import time;"
                    "from avelren.collector_spool import SpoolStore;"
                    "native=SpoolStore.set_capture_only;\n"
                    "def delayed(self,value):\n"
                    f" Path({driver.SPOOL!r}+'/before-set').touch()\n"
                    f" while not Path({driver.SPOOL!r}+'/release').exists(): time.sleep(.02)\n"
                    " native(self,value)\n"
                    "SpoolStore.set_capture_only=delayed\n"
                )
                command = ["python", "-c", gate + command[-1]]
            if kind == "check" and check == "running":
                command = ["python", "-c", "import time;time.sleep(120)"]
            return native_job(kind, image, options, command, output)

        runtime.job = job
        # Baseline's docker exec is delayed at precisely the same native mutation
        # boundary, allowing this regression to show its daemon lifetime gap.
        if delay is not None:
            native_mutation = runtime.controller.mutation_run

            def mutation(manifest, argv, **kw):
                if argv[1] == "exec" and "avelren.collector_control" in argv:
                    gate = (
                        "from pathlib import Path;import time;"
                        "from avelren.collector_spool import SpoolStore;"
                        "native=SpoolStore.set_capture_only;\n"
                        "def delayed(self,value):\n"
                        f" Path({driver.SPOOL!r}+'/before-set').touch()\n"
                        f" while not Path({driver.SPOOL!r}+'/release').exists(): time.sleep(.02)\n"
                        " native(self,value)\n"
                        "SpoolStore.set_capture_only=delayed\n"
                        "from avelren.collector_control import main;"
                        f"raise SystemExit(main(['capture-only',{delay!r}]))"
                    )
                    argv = [*argv[:3], "python", "-c", gate]
                return native_mutation(manifest, argv, **kw)

            runtime.controller.mutation_run = mutation
        if check == "created":
            native_output = runtime.output

            def output(argv, **kw):
                result = native_output(argv, **kw)
                if argv[1] == "create":
                    (self.root / "created").touch()
                    time.sleep(120)
                return result

            runtime.output = output
        return runtime

    def record(self, generation, phase, owner):
        return dict(format_version=1, generation=generation, phase=phase, owner=owner,
                    identity=self.identity, created_at=1.0, updated_at=2.0,
                    initial_capture_only=False, children=[])

    def wait_lock(self):
        deadline = time.monotonic() + 10
        while True:
            try:
                with state.backup_lock(self.directory):
                    return
            except ValueError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.02)

    def recover(self, generation):
        self.wait_lock()
        runtime = self.runtime()
        runtime.generation = generation
        with state.backup_lock(self.directory):
            return state.recover_owned_run(self.directory, runtime=runtime)

    def kill_owner(self, process):
        os.kill(process, signal.SIGKILL)
        os.waitpid(process, 0)

    def release(self):
        self.docker(["exec", self.collector, "touch", driver.SPOOL + "/release"])
        time.sleep(.3)
        self.assertFalse(self.status()["capture_only"], "late ON after terminal recovery")
        self.assertIs(self.status()["mode_ack"], False)

    def test_remote_before_set_on_and_off_owner_sigkill(self):
        for mode, boundary in (("on", "created"), ("on", "before-set"),
                               ("off", "created"), ("off", "before-set")):
            with self.subTest(mode=mode, boundary=boundary):
                (self.root / "created").unlink(missing_ok=True)
                self.docker(["exec", self.collector, "rm", "-f", driver.SPOOL + "/before-set",
                             driver.SPOOL + "/release"])
                if mode == "off":
                    self.docker(["exec", self.collector, "python", "-m",
                                 "avelren.collector_control", "capture-only", "on"])
                generation = str(uuid.uuid4())
                self.generations.append(generation)
                child = os.fork()
                if child == 0:
                    try:
                        runtime = self.runtime(delay=mode,
                                               check="created" if boundary == "created" else None)
                        runtime.generation = generation
                        with state.backup_lock(self.directory) as authority:
                            state.write_state(self.directory, self.record(
                                generation, mode + "_intent", authority.owner))
                            runtime.capture_only(mode, authority)
                        os._exit(1)
                    except BaseException:
                        os._exit(2)
                try:
                    if boundary == "created":
                        driver.wait(lambda: (self.root / "created").exists(), 10)
                    else:
                        driver.wait(lambda: bool(self.docker([
                            "exec", self.collector, "sh", "-c",
                            "test -e " + driver.SPOOL + "/before-set && echo ready || true"])), 10)
                    # Lease remains owned while the remote pre-mutation helper is live.
                    with self.assertRaisesRegex(ValueError, "backup_busy"):
                        with state.backup_lock(self.directory):
                            pass
                    name = "avelren-paired-" + generation + "-control-" + mode
                    owned = bool(self.docker(["ps", "-aq", "--filter",
                                              "name=^/" + name + "$"]).strip())
                finally:
                    self.kill_owner(child)
                self.wait_lock()
                with self.assertRaisesRegex(ValueError, "backup_recovery_required"):
                    with state.operator_guard(self.directory):
                        pass
                result = self.recover(generation)
                self.assertEqual(result["phase"], "resumed")
                self.assertFalse(self.docker(["ps", "-aq", "--filter",
                                             "name=^/" + name + "$"]).strip())
                self.release()
                self.assertTrue(owned, "remote mutation lacks an addressable owned daemon job")
                with state.operator_guard(self.directory):
                    pass

    def test_remote_before_set_timeout_uses_remaining_budget(self):
        generation = str(uuid.uuid4())
        self.generations.append(generation)
        runtime = self.runtime(delay="startup-on")
        runtime.generation = generation
        with state.backup_lock(self.directory) as authority:
            state.write_state(self.directory, self.record(generation, "on_intent", authority.owner))
            runtime.deadline = time.monotonic() + 2
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                runtime.capture_only("on", authority)
            self.assertLess(time.monotonic() - started, 4)
            self.assertTrue(self.docker([
                "exec", self.collector, "sh", "-c",
                "test -e " + driver.SPOOL + "/before-set && echo ready || true"]).strip(),
                "timeout must exercise a remote process delayed before mutation")
            self.assertTrue(self.docker(["ps", "-q", "--filter",
                                         "name=^/" + runtime.job_name("control-on") + "$"]).strip())
            # Timeout has stopped local CLI; production cancellation proves the remote lifetime.
            runtime.deadline = time.monotonic() + 20
            self.assertTrue(runtime.cancel_children([]))
        self.release()

    def test_preflight_death_created_and_running_no_state_and_old_terminal(self):
        for initial in ("none", "terminal"):
            for check in ("created", "running"):
                with self.subTest(initial=initial, check=check):
                    (self.directory / state.STATE_NAME).unlink(missing_ok=True)
                    (self.root / "created").unlink(missing_ok=True)
                    if initial == "terminal":
                        with state.backup_lock(self.directory) as authority:
                            state.write_state(self.directory, self.record(
                                str(uuid.uuid4()), "published", authority.owner))
                    child = os.fork()
                    if child == 0:
                        try:
                            runtime = self.runtime(check=check)
                            publisher = type("Publisher", (), {"preflight": lambda self: None})()
                            self.paired.Coordinator(
                                self.directory, self.work, runtime, publisher,
                                self.root / "receipt", self.root / "stamp").run()
                            os._exit(1)
                        except BaseException:
                            os._exit(2)
                    def check_ready(check=check):
                        value = state.read_state(self.directory)
                        if not value or value["phase"] != "prepared":
                            return False
                        self.generation = value["generation"]
                        name = "avelren-paired-" + self.generation + "-check"
                        ids = self.docker(["ps", "-aq", "--filter", "name=^/" + name + "$"])
                        if not ids.strip():
                            return False
                        actual = json.loads(self.docker(["inspect", name]))[0]["State"]["Status"]
                        return actual == check
                    try:
                        driver.wait(check_ready, 12)
                        self.generations.append(self.generation)
                    finally:
                        self.kill_owner(child)
                    self.assertEqual(self.recover(self.generation)["phase"], "resumed")
                    name = "avelren-paired-" + self.generation + "-check"
                    self.assertFalse(self.docker(["ps", "-aq", "--filter",
                                                 "name=^/" + name + "$"]).strip())
                    self.assertFalse(self.status()["capture_only"])

    def test_foreign_control_job_is_preserved_and_blocks_success(self):
        generation = str(uuid.uuid4())
        self.generations.append(generation)
        runtime = self.runtime()
        runtime.generation = generation
        name = runtime.job_name("control-on")
        self.names.append(name)
        self.docker(["create", "--name", name, "--network", "none", "--label",
                     "org.avelren.backup.generation=" + generation, "--label",
                     "org.avelren.backup.runtime=foreign", self.image, "python", "-c", "pass"])
        dead = dict(pid=2147483647, start_ticks=1,
                    boot_id=state.process_identity(os.getpid())["boot_id"])
        with state.backup_lock(self.directory):
            state.write_state(self.directory, self.record(generation, "on_intent", dead))
            self.assertEqual(state.recover_owned_run(self.directory, runtime=runtime)["phase"],
                             "recovery_required")
        self.assertTrue(self.docker(["ps", "-aq", "--filter", "name=^/" + name + "$"]).strip())
        self.assertFalse(self.status()["capture_only"])

    def test_initial_foreign_mode_and_generation_are_preserved(self):
        foreign = "avelren-paired-" + str(uuid.uuid4()) + "-control-on"
        self.names.append(foreign)
        self.docker(["create", "--name", foreign, "--network", "none", "--label",
                     "org.avelren.backup.generation=foreign", self.image, "python", "-c", "pass"])
        self.docker(["exec", self.collector, "python", "-m", "avelren.collector_control",
                     "capture-only", "on"])
        runtime = self.runtime()
        publisher = type("Publisher", (), {"preflight": lambda self: None})()
        with self.assertRaisesRegex(ValueError, "existing_or_uncertain_capture_mode"):
            self.paired.Coordinator(self.directory, self.work, runtime, publisher,
                                    self.root / "receipt", self.root / "stamp").run()
        self.assertIsNone(state.read_state(self.directory))
        self.assertTrue(self.status()["capture_only"])
        self.assertTrue(self.status()["mode_ack"])
        self.assertFalse(self.docker(["ps", "-aq", "--filter",
                                     "name=^/" + runtime.job_name("check") + "$"]).strip())
        # An unrelated generation also survives successful production recovery.
        self.docker(["exec", self.collector, "python", "-m", "avelren.collector_control",
                     "capture-only", "off"])
        generation = str(uuid.uuid4())
        self.generations.append(generation)
        dead = dict(pid=2147483647, start_ticks=1,
                    boot_id=state.process_identity(os.getpid())["boot_id"])
        with state.backup_lock(self.directory):
            state.write_state(self.directory, self.record(generation, "prepared", dead))
        self.assertEqual(self.recover(generation)["phase"], "resumed")
        self.assertTrue(self.docker(["ps", "-aq", "--filter", "name=^/" + foreign + "$"]).strip())


if __name__ == "__main__":
    unittest.main()
