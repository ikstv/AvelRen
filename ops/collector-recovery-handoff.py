"""Окремий fail-closed протокол recovery: prepare → switch → finish.

Не публікує backup і не створює ACK. Усі мутації CLI тримають обидві lease.
Після переривання повторюють ту саму команду з тими самими hash pins.
"""

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

JOURNAL = "collector-handoff.json"
TERMINAL = {"complete", "rolled_back"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Handoff:
    """Pure state machine; adapter persists every intent before side effects."""

    def __init__(self, adapter):
        self.a = adapter
        self.j = adapter.journal_read()

    def save(self, **changes):
        replacement = dict(self.j, **changes)
        self.a.journal_save(self.j, replacement)
        self.j = replacement

    def check(self):
        if self.j is None:
            raise ValueError("handoff_not_prepared")
        self.a.validate(self.j["expected_state"], self.j)

    def prepare(self):
        if self.j is None or self.j["phase"] == "rolled_back":
            previous = self.j
            plan = self.a.preflight()
            old = self.a.read()
            self.a.validate(old)
            self.j = dict(
                format_version=1,
                phase="stop_intent",
                plan=plan,
                old_state=old,
                expected_state=old,
                new_identity=None,
            )
            if previous is not None:
                self.j["previous_journal"] = previous
            self.a.journal_save(previous, self.j)
        self.check()
        if self.j["phase"] == "prepared":
            return self.j
        if self.j["phase"] != "stop_intent":
            raise ValueError("invalid_handoff_phase")
        self.a.cleanup()
        self.a.stop(self.j["old_state"]["identity"])
        self.check()
        safety = self.a.safety()
        self.check()
        self.save(phase="prepared", safety=safety)
        return self.j

    def switch(self):
        self.check()

        def stable(v):
            return {k: x for k, x in v.items() if k != "started_at"}

        if self.j["phase"] == "started":
            return self.j
        if self.j["phase"] not in {"prepared", "switch_intent", "start_intent"}:
            raise ValueError("invalid_handoff_phase")
        if self.j["phase"] != "start_intent":
            if self.a.identity() != self.j["old_state"]["identity"]:
                raise ValueError("identity_changed")
            self.save(phase="switch_intent")
            self.a.switch(self.j["plan"]["new"])
            self.save(phase="start_intent", created_identity=self.a.identity())
        else:
            actual = self.a.identity()
            if stable(actual) != stable(self.j["created_identity"]):
                raise ValueError("created_identity_changed")
            self.a.stop(actual)
        # Always a full monotonic interval, including after process death/reboot.
        self.a.wait()
        self.check()
        actual = self.a.identity()
        if actual != self.j["created_identity"]:
            # A resumed start_intent was stopped after the interrupted start;
            # StartedAt may differ, but container/restart identity cannot drift.
            if stable(actual) != stable(self.j["created_identity"]):
                raise ValueError("created_identity_changed")
        identity = self.a.start()
        self.save(phase="started", new_identity=identity)
        return self.j

    def finish(self):
        self.check()
        if self.j["phase"] == "complete":
            return self.a.read()
        if self.j["phase"] not in {"started", "off_intent", "state_intent", "terminal_intent"}:
            raise ValueError("invalid_handoff_phase")
        if self.a.identity(require_running=True) != self.j["new_identity"]:
            raise ValueError("identity_changed")
        if self.j["phase"] == "started":
            replacement = dict(
                self.j["expected_state"],
                identity=self.j["new_identity"],
                phase="off_intent",
                children=[],
            )
            replacement.pop("failure_reason", None)
            self.save(phase="state_intent", next_state=replacement)
        if self.j["phase"] == "state_intent":
            self.commit_state("off_intent")
        if self.j["phase"] == "off_intent":
            status = self.a.off()
            if (
                status.get("capture_only") is not False
                or status.get("mode_ack") is not False
                or status.get("pending_count") != 0
            ):
                raise ValueError("native_off_ack_and_drain_required")
            self.check()
            if self.a.identity(require_running=True) != self.j["new_identity"]:
                raise ValueError("identity_changed")
            replacement = dict(self.j["expected_state"], phase="resumed")
            self.save(phase="terminal_intent", next_state=replacement)
        if self.j["phase"] == "terminal_intent":
            self.check()
            if self.a.identity(require_running=True) != self.j["new_identity"]:
                raise ValueError("identity_changed")
            self.commit_state("complete")
        return self.a.read()

    def commit_state(self, phase):
        current = self.a.read()
        expected, replacement = self.j["expected_state"], self.j["next_state"]
        if current != replacement:
            self.a.state_save(expected, replacement)
        self.save(phase=phase, expected_state=replacement)

    def rollback(self):
        self.check()
        if self.j["phase"] == "rolled_back":
            return self.a.read()
        if self.j["phase"] == "rollback_state_intent":
            self.commit_state("rolled_back")
            return self.a.read()
        if self.j["phase"] not in {
            "prepared",
            "switch_intent",
            "start_intent",
            "started",
            "off_intent",
            "rollback_intent",
            "rollback_start_intent",
        }:
            raise ValueError("invalid_rollback_phase")
        if self.j["phase"] not in {"rollback_intent", "rollback_start_intent"}:
            pinned = (
                self.j.get("new_identity")
                or self.j.get("created_identity")
                or self.j["old_state"]["identity"]
            )
            if self.a.identity() != pinned:
                raise ValueError("identity_changed")
            self.save(phase="rollback_intent", rollback_from=pinned)
        if self.j["phase"] == "rollback_intent":
            if self.a.identity() != self.j["rollback_from"]:
                raise ValueError("identity_changed")
            self.a.stop(self.j["rollback_from"])
            counts = self.a.backlog()
            if counts.get("pending") != 0 or counts.get("started") != 0:
                raise ValueError("legacy_rollback_backlog")
            self.a.switch(self.j["plan"]["old"])
            self.save(phase="rollback_start_intent", rollback_created=self.a.identity())
        actual = self.a.identity()

        def stable(v):
            return {k: x for k, x in v.items() if k != "started_at"}

        if stable(actual) != stable(self.j["rollback_created"]):
            raise ValueError("identity_changed")
        self.a.stop(actual)
        self.a.wait()
        self.check()
        if self.a.identity() != actual:
            raise ValueError("identity_changed")
        counts = self.a.backlog()
        if counts.get("pending") != 0 or counts.get("started") != 0:
            raise ValueError("legacy_rollback_backlog")
        identity = self.a.start()
        replacement = dict(
            self.j["old_state"],
            identity=identity,
            phase="recovery_required",
            failure_reason="ownership_unproven",
            children=[],
        )
        self.save(phase="rollback_state_intent", next_state=replacement, new_identity=identity)
        self.commit_state("rolled_back")
        return self.a.read()


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class LocalAdapter:
    @classmethod
    def for_disposable(cls, args, state, control, paired, *, sql_project):
        return cls(args, state, control, paired, test_mode=True, sql_project=sql_project)

    def __init__(self, args, state, control, paired, *, test_mode=False, sql_project=None):
        self.args, self.state, self.control, self.paired = args, state, control, paired
        self.test_mode = test_mode
        uuid.UUID(args.generation)
        if any(
            not re.fullmatch("[0-9a-f]{64}", getattr(args, k))
            for k in ("state_sha256", "manifest_sha256", "new_manifest_sha256")
        ):
            raise ValueError("invalid_hash_pin")
        active = control.runtime.load_manifest(args.manifest, test_mode=test_mode)
        self.directory = Path(active["state_dir"])
        previous = self.journal_read()
        restart = (
            previous is not None
            and previous["phase"] == "rolled_back"
            and args.state_sha256 != previous["plan"]["state_sha256"]
        )
        self.old_manifest_text = (
            args.manifest.read_text()
            if previous is None or restart
            else previous["plan"]["old_manifest_text"]
        )
        if hashlib.sha256(self.old_manifest_text.encode()).hexdigest() != args.manifest_sha256:
            raise ValueError("old_manifest_audit_changed")
        self.old = json.loads(self.old_manifest_text)
        self.new = control.runtime.load_manifest(args.new_manifest, test_mode=test_mode)
        if any(
            self.old[k] != self.new[k] for k in self.old if k not in {"image_id", "source_commit"}
        ):
            raise ValueError("runtime_resource_drift")
        if self.old == self.new:
            raise ValueError("new_identity_required")
        if self.directory != Path(self.old["state_dir"]):
            raise ValueError("state_directory_changed")
        self.work = self.directory / ("handoff-" + args.generation)
        self.runtime = paired.Runtime(self.old, self.work, args.stack)
        if test_mode:
            if sql_project != self.old["project"] + "-sql":
                raise ValueError("disposable_sql_project_mismatch")
            self.runtime._sql_project = sql_project
        self.runtime.generation = args.generation
        self.current = self.old
        self.runtime.identity = self.identity
        # Helpers are authorized by the persisted journal rather than by a
        # running collector; safety capture intentionally uses a stopped writer.
        self.runtime.owned_job_record = self.owned_job_record
        self.bound_files = (
            {k: digest(self.old[k]) for k in ("env_file", "compose_file")}
            if previous is None or restart
            else previous["plan"]["bound_files"]
        )

    def read(self):
        return self.state.read_state(self.directory)

    def private_read(self, path):
        self.control.runtime.private_path(path)
        if path.stat().st_nlink != 1:
            raise ValueError("unsafe_audit_path")
        return json.loads(path.read_text())

    def journal_read(self):
        path = self.directory / JOURNAL
        return self.private_read(path) if path.exists() or path.is_symlink() else None

    def atomic(self, path, value):
        self.state.validate_authority(self.state._authority(self.directory), self.directory)
        if path.exists() or path.is_symlink():
            self.private_read(path)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            temporary = ".handoff-" + uuid.uuid4().hex
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=directory_fd,
            )
            try:
                with os.fdopen(fd, "w") as stream:
                    json.dump(value, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
                os.fsync(directory_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory_fd)

    def journal_save(self, expected, value):
        if self.journal_read() != expected:
            raise ValueError("journal_changed")
        self.atomic(self.directory / JOURNAL, value)

    def state_save(self, expected, replacement):
        if self.read() != expected:
            raise ValueError("state_changed")
        self.state.write_state(self.directory, replacement)

    def pins(self):
        return dict(
            generation=self.args.generation,
            state_sha256=self.args.state_sha256,
            manifest_sha256=self.args.manifest_sha256,
            new_manifest_sha256=self.args.new_manifest_sha256,
            old=self.old,
            new=self.new,
            old_manifest_text=self.old_manifest_text,
            bound_files=self.bound_files,
        )

    def validate(self, expected, journal=None):
        self.state.validate_authority(self.state._authority(self.directory), self.directory)
        actual = self.read()
        # A durable state-write intent permits exactly its before/after values.
        allowed = [expected]
        if journal and journal["phase"] in {
            "state_intent",
            "terminal_intent",
            "rollback_state_intent",
        }:
            allowed.append(journal["next_state"])
        if actual not in allowed:
            raise ValueError("state_changed")
        if journal and journal.get("safety"):
            self.verify_safety(journal["safety"])
        if not self.state._owner_dead(expected["owner"]):
            raise ValueError("owner_unproven")
        for child in expected["children"]:
            if not self.state._owner_dead(child):
                raise ValueError("child_unproven")
        self.jobs(remove=False)
        if journal and journal["plan"] != self.pins():
            raise ValueError("plan_changed")
        if any(digest(self.old[k]) != v for k, v in self.bound_files.items()):
            raise ValueError("env_or_compose_changed")
        if digest(self.args.new_manifest) != self.args.new_manifest_sha256:
            raise ValueError("new_manifest_changed")
        original_hash = self.args.manifest_sha256
        active = digest(self.args.manifest)
        allowed_hashes = {original_hash}
        if journal:
            allowed_hashes.add(hashlib.sha256(self.encoded(self.new)).hexdigest())
            allowed_hashes.add(hashlib.sha256(self.encoded(self.old)).hexdigest())
        if active not in allowed_hashes:
            raise ValueError("manifest_changed")

    @staticmethod
    def encoded(value):
        return json.dumps(value, sort_keys=True).encode()

    def preflight(self):
        value = self.read()
        if (
            value is None
            or value["generation"] != self.args.generation
            or value["phase"] != "recovery_required"
            or value["initial_capture_only"]
            or digest(self.directory / self.state.STATE_NAME) != self.args.state_sha256
            or digest(self.args.manifest) != self.args.manifest_sha256
            or digest(self.args.new_manifest) != self.args.new_manifest_sha256
            or not self.state._owner_dead(value["owner"])
        ):
            raise ValueError("stale_owner_or_pin_unproven")
        for child in value["children"]:
            if not self.state._owner_dead(child):
                raise ValueError("live_or_reused_child")
        self.current = self.old
        if self.identity() != value["identity"]:
            raise ValueError("old_identity_changed")
        self.jobs(remove=False)
        # Verify candidate image, compose security and external resources before
        # stopping anything. Runtime validation compares candidate against a
        # synthetic copy of the exact target, with only image/source substituted.
        _, target = self.control.runtime.preflight(self.old)
        cmd, env = self.control.runtime.compose_command(self.new)
        effective = json.loads(
            self.compose_output(
                self.new, [*cmd, "config", "--format", "json", "--no-env-resolution"], env
            )
        )
        inventory = self.control.runtime.inspect_inventory()
        proposed = copy.deepcopy(target)
        proposed["Image"] = self.new["image_id"]
        proposed["Config"]["Env"] = [
            line for line in proposed["Config"]["Env"] if not line.startswith("AVELREN_GIT_SHA=")
        ]
        proposed["Config"]["Env"].append("AVELREN_GIT_SHA=" + self.new["source_commit"])
        inventory = [proposed if x["Id"] == target["Id"] else x for x in inventory]
        if self.control.runtime.validate_runtime(
            self.new, effective, inventory, require_managed=True
        ):
            raise ValueError("candidate_runtime_invalid")
        image = json.loads(
            self.runtime.output(["docker", "image", "inspect", self.new["image_id"]])
        )
        if (
            len(image) != 1
            or image[0]["Id"] != self.new["image_id"]
            or "AVELREN_GIT_SHA=" + self.new["source_commit"]
            not in image[0]["Config"].get("Env", [])
        ):
            raise ValueError("candidate_image_source_invalid")
        return self.pins()

    def compose_output(self, manifest, argv, env):
        # Runtime.output deliberately rebuilds its environment from manifest.
        # Bind the requested image/source while executing that sanitized command.
        previous = self.runtime.manifest
        self.runtime.manifest = manifest
        try:
            return self.runtime.output(argv, env=env)
        finally:
            self.runtime.manifest = previous

    def verify_safety(self, safety):
        capture = Path(safety["directory"])
        if capture.parent != self.work or not capture.name.startswith("safety-"):
            raise ValueError("unsafe_safety_directory")
        self.state._private(capture.lstat(), directory=True)
        if capture.is_symlink():
            raise ValueError("unsafe_safety_directory")
        names = {
            "sql": "avelren-safety.sql.gz",
            "spool": "avelren-safety.spool.sqlite3.gz",
            "rollback": "rollback.json",
        }
        for kind, name in names.items():
            path = capture / name
            self.state._private(path.lstat())
            if digest(path) != safety[kind]:
                raise ValueError("safety_artifact_changed")
            if kind == "rollback":
                json.loads(path.read_text())
            else:
                with gzip.open(path, "rb") as stream:
                    if not stream.read(1):
                        raise ValueError("empty_safety_artifact")
                    while stream.read(1024 * 1024):
                        pass

    def read_only_output(self, argv, *, env=None):
        """Dry-run has no work directory/helper writes; only bounded read commands."""
        collector = self.runtime.manifest if self.runtime.manifest["compose_file"] in argv else None
        result = subprocess.run(
            argv,
            env=self.paired.command_environment(docker=True, collector=collector),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode:
            raise ValueError("read_command_failed")
        return result.stdout

    def target(self):
        inventory = self.control.runtime.inspect_inventory()
        targets = [x for x in inventory if x.get("Name") == "/" + self.old["container_name"]]
        if len(targets) != 1:
            raise ValueError("target_missing_or_ambiguous")
        item = targets[0]
        matches = [m for m in (self.old, self.new) if m["image_id"] == item["Image"]]
        if len(matches) != 1:
            raise ValueError("unexpected_image")
        self.current = matches[0]
        self.runtime.manifest = self.current
        _, checked = self.control.runtime.preflight(self.current)
        return checked

    def identity(self, *, require_running=False):
        item = self.target()
        if require_running and not item["State"]["Running"]:
            raise ValueError("collector_stopped")
        return dict(
            container_id=item["Id"],
            image_id=item["Image"],
            source_commit=self.current["source_commit"],
            restart_count=item["RestartCount"],
            started_at=item["State"]["StartedAt"],
            volume=self.current["volume"],
            network=self.current["network"],
        )

    def jobs(self, *, remove):
        value = self.read()
        identities = [value["identity"]]
        journal = self.journal_read()
        if journal:
            identities.extend(
                journal[k]
                for k in ("created_identity", "new_identity", "rollback_from", "rollback_created")
                if journal.get(k)
            )
        runtime_pins = {
            hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            for identity in identities
        }
        kinds = {
            "check",
            "sql",
            "spool",
            "control-on",
            "control-off",
            "handoff-migrate",
            "handoff-status",
        }
        for item in self.control.runtime.inspect_inventory():
            labels = item.get("Config", {}).get("Labels") or {}
            name = item.get("Name", "").lstrip("/")
            relevant = name.startswith("avelren-paired-") or any(
                k.startswith("org.avelren.backup.") for k in labels
            )
            if not relevant:
                continue
            if (
                name not in {"avelren-paired-" + value["generation"] + "-" + k for k in kinds}
                or labels.get("org.avelren.backup.generation") != value["generation"]
                or labels.get("org.avelren.backup.runtime") not in runtime_pins
                or item.get("State", {}).get("Running")
                or item.get("State", {}).get("Paused")
                or item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") not in ("no", "")
            ):
                raise ValueError("foreign_ambiguous_or_live_job")
            if remove:
                again = json.loads(self.runtime.output(["docker", "inspect", item["Id"]]))
                if again != [item]:
                    raise ValueError("job_changed")
                self.runtime.output(["docker", "rm", item["Id"]])

    def cleanup(self):
        self.jobs(remove=True)

    def owned_job_record(self):
        j = self.journal_read()
        if j is None or j["phase"] in TERMINAL:
            raise ValueError("handoff_lease_required")
        self.validate(j["expected_state"], j)
        return self.read()

    def mutation_guard(self):
        j = self.journal_read()
        if j is None:
            raise ValueError("handoff_lease_required")
        self.validate(j["expected_state"], j)
        self.runtime.verify_client()

    def stop(self, identity):
        self.mutation_guard()
        actual = self.identity()
        if actual != identity:
            raise ValueError("identity_changed")
        target = self.target()
        if target["State"]["Running"]:
            self.runtime.output(["docker", "stop", "--time", "30", target["Id"]])
        if self.target()["State"]["Running"]:
            raise ValueError("stop_not_confirmed")

    def safety(self):
        if self.target()["State"]["Running"]:
            raise ValueError("writer_running")
        # New attempt directory is retained on every interruption, never reused.
        capture = self.work / ("safety-" + uuid.uuid4().hex)
        capture.mkdir(mode=0o700)
        self.runtime.verify_client()
        self.runtime.verify_helper_image()
        self.runtime.prepare_sql()
        self.runtime.identity = self.identity
        sql = self.runtime.sql_snapshot(capture, "safety", self.args.generation)
        spool, summary = self.runtime.spool_snapshot(capture, "safety", self.args.generation)
        if self.runtime.cancel_jobs(["sql", "spool"]) is not True:
            raise ValueError("safety_jobs_unresolved")
        rollback = capture / "rollback.json"
        self.atomic(
            rollback, {"manifest": self.old, "state": self.read(), "target": self.redacted_target()}
        )
        # Persist capture contents and their directory entries before migration
        # can change the original spool. The rollback file was synced by atomic.
        for path, directory in ((sql, False), (spool, False), (capture, True), (self.work, True)):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            if directory:
                flags |= os.O_DIRECTORY
            fd = os.open(path, flags)
            try:
                self.state._private(os.fstat(fd), directory=directory)
                os.fsync(fd)
            finally:
                os.close(fd)
        # Verified legacy provenance is written by the reviewed offline module,
        # after immutable SQL/SQLite safety capture and before the first new cycle.
        self.migrate()
        return {
            "directory": str(capture),
            "sql": digest(sql),
            "spool": digest(spool),
            "rollback": digest(rollback),
            "summary": summary,
        }

    def redacted_target(self):
        item = self.target()
        return {k: item[k] for k in ("Id", "Image", "RestartCount", "State")}

    def migrate(self):
        output = self.work / (".migration-" + uuid.uuid4().hex)
        self.runtime.job(
            "handoff-migrate",
            self.new["image_id"],
            [
                "--network",
                self.old["network"],
                "--env-file",
                self.old["env_file"],
                "--user",
                "10001:10001",
                "--mount",
                "type=volume,src=" + self.old["volume"] + ",dst=/var/lib/avelren/collector-spool",
            ],
            [
                "python",
                "-c",
                "from avelren import collector_spool_migration as m; m.main()",
                "--spool",
                "/var/lib/avelren/collector-spool/cycles.sqlite3",
                "--source-commit",
                self.old["source_commit"],
                "--image-id",
                self.old["image_id"],
            ],
            output,
        )
        if self.runtime.cancel_jobs(["handoff-migrate"]) is not True:
            raise ValueError("migration_job_unresolved")

    def switch(self, manifest):
        self.mutation_guard()
        item = self.target()
        if item["State"]["Running"]:
            # An interrupted start is stopped and waits a fresh interval.
            self.stop(self.identity())
        if item["Image"] != manifest["image_id"]:
            cmd, env = self.control.runtime.compose_command(manifest)
            self.compose_output(
                manifest,
                [
                    *cmd,
                    "up",
                    "--no-start",
                    "--no-deps",
                    "--no-build",
                    "--pull",
                    "never",
                    "--force-recreate",
                    "collector",
                ],
                env,
            )
        self.current = manifest
        self.runtime.manifest = manifest
        target = self.target()
        if target["State"]["Running"] or self.current != manifest:
            raise ValueError("switch_not_confirmed")
        self.atomic(self.args.manifest, manifest)

    def wait(self):
        self.control.wait_interval(60)

    def start(self):
        self.mutation_guard()
        item = self.target()
        if item["State"]["Running"]:
            raise ValueError("unexpected_running_writer")
        self.runtime.output(["docker", "start", item["Id"]])
        if not self.target()["State"]["Running"]:
            raise ValueError("start_not_confirmed")
        return self.identity()

    def off(self):
        self.mutation_guard()
        self.cleanup()
        # operator_lock is already held. Native helper retains bounded job
        # supervision; its result must contain the writer's native ACK.
        mode = self.control._execute(
            self.current, "capture-only", ["off"], capture_mutation=self.runtime.control_job
        )
        deadline = min(self.runtime.deadline, time.monotonic() + 120)
        while True:
            if mode.get("last_error") is not None:
                raise ValueError("collector_drain_error")
            if (
                mode.get("capture_only") is False
                and mode.get("mode_ack") is False
                and mode.get("pending_count") == 0
            ):
                return mode
            if time.monotonic() >= deadline:
                raise ValueError("collector_drain_timeout")
            time.sleep(1)
            mode = self.runtime.capture_status()

    def backlog(self):
        self.mutation_guard()
        self.cleanup()
        # SQL is read-only; a writable mount permits WAL/shm coordination
        # after the last writer closes. Leases and stopped writer are required.
        path = self.work / (".backlog-" + uuid.uuid4().hex)
        self.runtime.job(
            "handoff-status",
            self.new["image_id"],
            [
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--mount",
                "type=volume,src="
                + self.old["volume"]
                + ",dst=/var/lib/avelren/collector-spool",
            ],
            [
                "python",
                "-c",
                "import sqlite3,json; c=sqlite3.connect("
                "'file:/var/lib/avelren/collector-spool/cycles.sqlite3?mode=ro',uri=True); "
                "print(json.dumps(dict(c.execute("
                "'SELECT state,count(*) FROM cycles GROUP BY state'))))",
            ],
            path,
        )
        counts = json.loads(path.read_text())
        if self.runtime.cancel_jobs(["handoff-status"]) is not True:
            raise ValueError("status_job_unresolved")
        return {"pending": counts.get("pending", 0), "started": counts.get("started", 0)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["dry-run", "prepare", "switch", "finish", "rollback"])
    for name in ("manifest", "new-manifest", "stack"):
        p.add_argument("--" + name, type=Path, required=True)
    for name in ("generation", "state-sha256", "manifest-sha256", "new-manifest-sha256"):
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    try:
        state = load("paired_backup_state", "paired_backup_state.py")
        control = load("handoff_control", "collector-runtime-control.py")
        paired = load("handoff_paired", "paired-backup.py")
        a = LocalAdapter(args, state, control, paired)
        with state.backup_lock(a.directory), control.operator_lock(a.directory):
            if args.command == "dry-run":
                a.runtime.output = a.read_only_output
                a.runtime.controller.runtime.run = a.read_only_output
                control.runtime.run = a.read_only_output
                print(json.dumps({"status": "verified", "plan": a.preflight()}))
                return 0
            a.work.mkdir(mode=0o700, exist_ok=True)
            control.runtime.private_path(a.work, directory=True)
            a.runtime.deadline = time.monotonic() + 900
            result = getattr(Handoff(a), args.command)()
            print(json.dumps({"status": result["phase"], "generation": args.generation}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        print(json.dumps({"status": "denied", "reason": "handoff_verification_failed"}))
        return 75
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
