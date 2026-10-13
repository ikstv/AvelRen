#!/usr/bin/env python3
"""Узгоджений backup; лише confirmed off ACK дозволяє publication."""

import argparse
import gzip
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import signal
import stat
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import paired_backup_manifest as pair
import paired_backup_state as state

NETWORK_SECONDS = 900
DRAIN_POLL_SECONDS = 1


class BackupError(ValueError):
    """Категорія без raw writer errors або приватних значень."""


def utc():
    return datetime.now(UTC).isoformat()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def private_directory(path):
    fd = state._directory(path)
    os.close(fd)


def private_file(path, data):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def safe_destination(path, work):
    if not path.is_absolute() or path.resolve().is_relative_to(work.resolve()):
        raise ValueError("unsafe_evidence_path")
    # /run is not private, but must be a trusted root-owned hierarchy.
    for parent in (path.parent, *path.parent.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("unsafe_evidence_path")
    if path.exists() or path.is_symlink():
        state._private(path.lstat())


def atomic_evidence(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".paired-evidence-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Coordinator:
    def __init__(self, state_dir, work_dir, runtime, publisher, receipt, stamp):
        self.state_dir, self.work_dir = Path(state_dir), Path(work_dir)
        self.runtime, self.publisher = runtime, publisher
        self.receipt, self.stamp = Path(receipt), Path(stamp)
        self.value = None
        self.writer_status = []

    def await_drain(self, stage):
        while True:
            if time.monotonic() >= self.network_deadline:
                raise BackupError("drain_timeout")
            if self.runtime.identity() != self.value["identity"]:
                raise BackupError("identity_changed")
            status = self.runtime.capture_status()
            pending, acked = status.get("pending_count"), status.get("acked_count")
            if type(pending) is not int or pending < 0 or type(acked) is not int or acked < 0:
                raise BackupError("writer_status_invalid")
            summary = dict(
                stage=stage,
                pending_count=pending,
                acked_count=acked,
                last_error_present=status.get("last_error") is not None,
                capture_only=status.get("capture_only"),
                mode_ack=status.get("mode_ack"),
            )
            if summary["capture_only"] is not False or summary["mode_ack"] is not False:
                raise BackupError("writer_mode_changed")
            if summary["last_error_present"]:
                raise BackupError("writer_error")
            if time.monotonic() >= self.network_deadline:
                raise BackupError("drain_timeout")
            if pending == 0:
                self.writer_status.append(summary)
                return
            time.sleep(min(DRAIN_POLL_SECONDS, max(0, self.network_deadline - time.monotonic())))

    def phase(self, name, reason=None):
        self.value.update(phase=name, updated_at=time.time())
        if reason:
            self.value["failure_reason"] = reason
        else:
            self.value.pop("failure_reason", None)
        state.write_state(self.state_dir, self.value)

    def resume(self, authority):
        state.validate_authority(authority, self.state_dir)
        if state.read_state(self.state_dir) != self.value:
            raise ValueError("ownership_unproven")
        if self.runtime.identity() != self.value["identity"]:
            raise ValueError("identity_changed")
        if self.runtime.cancel_children(self.value["children"]) is not True:
            raise ValueError("children_unresolved")
        if state.read_state(self.state_dir) != self.value:
            raise ValueError("ownership_unproven")
        if self.runtime.identity() != self.value["identity"]:
            raise ValueError("identity_changed")
        mode = self.runtime.capture_status()
        if mode.get("capture_only") is True:
            self.phase("off_intent")
            mode = self.runtime.capture_only("off", authority)
        if mode.get("capture_only") is not False or mode.get("mode_ack") is not False:
            raise ValueError("off_unacknowledged")
        if self.runtime.identity() != self.value["identity"]:
            raise ValueError("identity_changed")
        self.phase("resumed")

    def run(self):
        private_directory(self.work_dir)
        safe_destination(self.receipt, self.work_dir)
        safe_destination(self.stamp, self.work_dir)
        state.require_process_supervision()
        with state.backup_lock(self.state_dir) as authority:
            old = state.read_state(self.state_dir)
            if old is not None and old["phase"] not in state.TERMINAL:
                self.runtime.generation = old["generation"]
                recovered = state.recover_owned_run(self.state_dir, runtime=self.runtime)
                if recovered["phase"] not in state.TERMINAL:
                    raise ValueError("backup_recovery_required")
            generation = str(uuid.uuid4())
            self.runtime.generation = generation
            self.runtime.deadline = time.monotonic() + 180
            directory = Path(tempfile.mkdtemp(prefix=".paired-", dir=self.work_dir))
            try:
                self.runtime.preflight()
                self.publisher.preflight()
                identity = self.runtime.identity()
                mode = self.runtime.capture_status()
                if mode.get("capture_only") is not False or mode.get("mode_ack") is not False:
                    raise ValueError("existing_or_uncertain_capture_mode")
                now = time.time()
                self.value = dict(
                    format_version=1,
                    generation=generation,
                    owner=authority.owner,
                    identity=identity,
                    phase="prepared",
                    created_at=now,
                    updated_at=now,
                    initial_capture_only=False,
                    children=[],
                )
                state.write_state(self.state_dir, self.value)
                self.receipt.unlink(missing_ok=True)
                started = time.monotonic()
                pause_deadline = started + 900
                self.runtime.deadline = started + 720
                self.phase("on_intent")
                mode = self.runtime.capture_only("on", authority)
                if mode.get("capture_only") is not True or mode.get("mode_ack") is not True:
                    raise ValueError("on_unacknowledged")
                self.phase("paused")
                backup_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
                snapshots = {"sql": {"started_at": utc()}}
                sql = self.runtime.sql_snapshot(directory, backup_id, generation)
                snapshots["sql"]["finished_at"] = utc()
                snapshots["spool"] = {"started_at": utc()}
                spool, summary = self.runtime.spool_snapshot(directory, backup_id, generation)
                snapshots["spool"]["finished_at"] = utc()
                if time.monotonic() >= self.runtime.deadline:
                    raise ValueError("command_timeout")
                if self.runtime.identity() != identity:
                    raise ValueError("identity_changed")
                mode = self.runtime.capture_status()
                if mode.get("capture_only") is not True or mode.get("mode_ack") is not True:
                    raise ValueError("capture_mode_changed")
                self.phase("copied")
                self.runtime.deadline = pause_deadline
                self.resume(authority)
                pause_seconds = time.monotonic() - started
                self.network_deadline = time.monotonic() + NETWORK_SECONDS
                self.runtime.deadline = self.network_deadline
                self.publisher.deadline = self.network_deadline
                self.publisher.before_manifest = lambda: self.await_drain("before_manifest")
                self.await_drain("resumed")
                artifacts = {}
                for key, path in [("sql", sql), ("spool", spool)]:
                    artifacts[key] = dict(
                        name=path.name, sha256=digest(path), bytes=path.stat().st_size
                    )
                    private_file(
                        Path(str(path) + ".sha256"),
                        f"{artifacts[key]['sha256']}  {path.name}\n".encode(),
                    )
                manifest = pair.build_manifest(
                    backup_id,
                    artifacts,
                    snapshots,
                    {
                        k: identity[k]
                        for k in [
                            "source_commit",
                            "image_id",
                            "container_id",
                            "restart_count",
                            "started_at",
                        ]
                    },
                    summary,
                    True,
                )
                pair.verify_local_pair(manifest, directory)
                completion = directory / f"avelren-{backup_id}.pair.json"
                private_file(completion, json.dumps(manifest, sort_keys=True).encode())
                paths = self.publisher.publish(manifest, directory)
                self.await_drain("published")
                receipt = dict(
                    status="paired_backup_verified",
                    backup_id=backup_id,
                    manifest_sha256=digest(completion),
                    remote_paths=paths,
                    writer_resumed=True,
                    pause_seconds=round(pause_seconds, 3),
                    snapshots=snapshots,
                    state_counts=summary["state_counts"],
                    writer_status=self.writer_status,
                )
                self.phase("published")
                shutil.rmtree(directory)
                atomic_evidence(self.receipt, json.dumps(receipt, sort_keys=True).encode())
                atomic_evidence(self.stamp, (utc() + "\n").encode())
                return receipt
            except BaseException as exc:
                # Block repeated signals until owned cleanup has used its reserve.
                saved = {
                    s: signal.signal(s, signal.SIG_IGN)
                    for s in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM)
                }
                try:
                    if self.value is not None:
                        self.receipt.unlink(missing_ok=True)
                    if self.value is not None:
                        if self.value["phase"] in state.TERMINAL:
                            self.phase("resumed", "network_failed")
                        else:
                            self.runtime.deadline = min(
                                locals().get("pause_deadline", time.monotonic() + 180),
                                time.monotonic() + 180,
                            )
                            try:
                                self.resume(authority)
                                self.phase(
                                    "resumed",
                                    "cancelled"
                                    if isinstance(exc, KeyboardInterrupt)
                                    else "copy_failed",
                                )
                            except (ValueError, OSError, KeyError, TypeError) as cleanup:
                                category = str(cleanup)
                                if category not in {
                                    "identity_changed",
                                    "ownership_unproven",
                                    "children_unresolved",
                                    "off_unacknowledged",
                                }:
                                    category = "off_unacknowledged"
                                self.phase("recovery_required", category)
                    else:
                        self.runtime.cancel_children([])
                finally:
                    for sig, handler in saved.items():
                        signal.signal(sig, handler)
                raise
            finally:
                if directory.exists():
                    shutil.rmtree(directory)


class Publisher:
    def __init__(self, remote, config, work):
        if not re.fullmatch(r"[A-Za-z0-9_-]+:[A-Za-z0-9_/-]+", remote) or ".." in remote:
            raise ValueError("invalid_crypt_remote")
        self.remote, self.config, self.work = remote.rstrip("/"), config, work
        self.deadline = time.monotonic() + 90
        self.before_manifest = lambda: None

    def command(self, arguments, output=None):
        code = state.run_bounded(
            [
                "rclone",
                *arguments,
                "--config",
                str(self.config),
                "--retries",
                "1",
                "--low-level-retries",
                "1",
                "--timeout",
                "30s",
            ],
            deadline=self.deadline,
            stdout_path=output,
        )
        if code:
            raise ValueError("remote_operation_failed")

    def read(self, arguments):
        path = self.work / (".remote-" + uuid.uuid4().hex)
        try:
            self.command(arguments, path)
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    def preflight(self):
        config = self.read(["config", "show", self.remote.split(":")[0]]).decode()
        if re.findall(r"^\s*type\s*=\s*(\S+)\s*$", config, flags=re.M) != ["crypt"]:
            raise ValueError("crypt_required")

    def verify_file(self, path, remote_path):
        size = json.loads(self.read(["size", remote_path, "--json"]))
        if size.get("count") != 1 or size.get("bytes") != path.stat().st_size:
            raise ValueError("remote_size_mismatch")
        downloaded = self.work / (".remote-" + uuid.uuid4().hex)
        try:
            self.command(["cat", remote_path], downloaded)
            if downloaded.stat().st_size != path.stat().st_size or digest(downloaded) != digest(
                path
            ):
                raise ValueError("remote_hash_mismatch")
        finally:
            downloaded.unlink(missing_ok=True)

    def verify_record(self, manifest, prefix):
        # Verify every file before this record may contribute to retention.
        for artifact in manifest["artifacts"].values():
            size = json.loads(self.read(["size", prefix + artifact["name"], "--json"]))
            if size.get("count") != 1 or size.get("bytes") != artifact["bytes"]:
                raise ValueError("remote_pair_incomplete")
            path = self.work / (".remote-" + uuid.uuid4().hex)
            try:
                self.command(["cat", prefix + artifact["name"]], path)
                if path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
                    raise ValueError("remote_pair_corrupt")
            finally:
                path.unlink(missing_ok=True)
            expected = f"{artifact['sha256']}  {artifact['name']}\n".encode()
            if self.read(["cat", prefix + artifact["name"] + ".sha256"]) != expected:
                raise ValueError("remote_sidecar_invalid")

    def publish(self, manifest, directory):
        prefix = self.remote + "/" + manifest["tier"] + "/"
        paths = []
        for artifact in manifest["artifacts"].values():
            for name in [artifact["name"], artifact["name"] + ".sha256"]:
                path = directory / name
                self.command(["copyto", str(path), prefix + name])
                paths.append(prefix + name)
        for artifact in manifest["artifacts"].values():
            for name in [artifact["name"], artifact["name"] + ".sha256"]:
                self.verify_file(directory / name, prefix + name)
        name = f"avelren-{manifest['backup_id']}.pair.json"
        self.before_manifest()
        self.command(["copyto", str(directory / name), prefix + name])
        self.verify_file(directory / name, prefix + name)
        if pair.load_manifest(self.read(["cat", prefix + name])) != manifest:
            raise ValueError("manifest_readback_failed")
        paths.append(prefix + name)
        listing = self.read(
            ["lsf", prefix, "--files-only", "--include", "avelren-*.pair.json"]
        ).decode()
        records = []
        for candidate in listing.splitlines():
            if not re.fullmatch(r"avelren-[0-9]{8}-[0-9]{6}\.pair\.json", candidate):
                continue
            try:
                value = pair.load_manifest(self.read(["cat", prefix + candidate]))
                if (
                    value["tier"] != manifest["tier"]
                    or candidate != f"avelren-{value['backup_id']}.pair.json"
                ):
                    continue
                self.verify_record(value, prefix)
                records.append(value)
            except pair.ManifestError:
                continue
        keep = {"daily": 7, "weekly": 4, "monthly": 3}[manifest["tier"]]
        for backup_id in pair.retention_candidates(records, manifest["tier"], keep):
            if backup_id == manifest["backup_id"]:
                raise ValueError("retention_newest_protected")
            # Remove the completion marker first; partial deletion is never accepted.
            names = [f"avelren-{backup_id}.pair.json"]
            for suffix in ["sql.gz", "spool.sqlite3.gz"]:
                names.extend(
                    [f"avelren-{backup_id}.{suffix}", f"avelren-{backup_id}.{suffix}.sha256"]
                )
            for old in names:
                self.command(["deletefile", prefix + old])
        return paths


def load_controller():
    spec = importlib.util.spec_from_file_location(
        "paired_controller", Path(__file__).with_name("collector-runtime-control.py")
    )
    controller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(controller)
    return controller


class Runtime:
    def __init__(self, manifest, work, stack=None):
        self.manifest, self.work, self.stack = manifest, work, stack
        self.controller = load_controller()
        self.deadline = time.monotonic() + 180
        self.generation = None
        # The validated controller keeps its existing capability/lock checks.
        # Every nested subprocess consumes the coordinator's remaining budget.
        self.controller.runtime.run = self.output
        self.controller.mutation_run = lambda manifest, argv, env=None: self.output(argv, env=env)

    def output(self, argv, *, env=None):
        path = self.work / (".command-" + uuid.uuid4().hex)
        try:
            code = state.run_bounded(argv, deadline=self.deadline, env=env, stdout_path=path)
            if code:
                raise ValueError("command_failed")
            return path.read_text()
        finally:
            path.unlink(missing_ok=True)

    def identity(self):
        _, target = self.controller.runtime.preflight(self.manifest)
        if not target["State"]["Running"]:
            raise ValueError("collector_stopped")
        return dict(
            container_id=target["Id"],
            image_id=target["Image"],
            source_commit=self.manifest["source_commit"],
            restart_count=target["RestartCount"],
            started_at=target["State"]["StartedAt"],
            volume=self.manifest["volume"],
            network=self.manifest["network"],
        )

    def capture_status(self):
        return self.controller.execute(self.manifest, "capture-only", ["status"])

    def capture_only(self, mode, authority):
        original = self.deadline
        self.deadline = min(original, time.monotonic() + 35)
        try:
            return self.controller.execute(
                self.manifest, "capture-only", [mode], authority=authority
            )
        finally:
            self.deadline = original

    def job_name(self, kind):
        return "avelren-paired-" + self.generation + "-" + kind

    def labels(self):
        identity = hashlib.sha256(json.dumps(self.identity(), sort_keys=True).encode()).hexdigest()
        return {
            "org.avelren.backup.generation": self.generation,
            "org.avelren.backup.runtime": identity,
        }

    def job(self, kind, image, options, command, output):
        name = self.job_name(kind)
        labels = self.labels()
        argv = ["docker", "create", "--name", name, "--restart", "no"]
        for key, value in labels.items():
            argv.extend(["--label", key + "=" + value])
        identifier = self.output(
            [*argv, *options, "--entrypoint", command[0], image, *command[1:]],
            env=dict(os.environ, PGPASSWORD=os.environ.get("AVELREN_BACKUP_PASSWORD", "")),
        ).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise ValueError("invalid_helper_identity")
        code = state.run_bounded(
            ["docker", "start", "-a", identifier], deadline=self.deadline, stdout_path=output
        )
        if code:
            raise ValueError("helper_failed")
        found = json.loads(self.output(["docker", "inspect", identifier]))
        if len(found) != 1 or found[0]["State"]["Running"] or found[0]["State"]["ExitCode"] != 0:
            raise ValueError("helper_not_finished")

    def cancel_children(self, children):
        # run_bounded has reaped local descendants before returning. Do not
        # signal unrelated numeric PIDs from a stale record.
        for child in children:
            try:
                if state.process_identity(child["pid"]) == child:
                    return False
            except FileNotFoundError:
                pass
        expected = self.labels()
        for kind in ["check", "sql", "spool"]:
            name = self.job_name(kind)
            ids = self.output(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"]).split()
            if not ids:
                continue
            if len(ids) != 1:
                return False
            found = json.loads(self.output(["docker", "inspect", ids[0]]))
            if len(found) != 1:
                return False
            job = found[0]
            if job.get("Name") != "/" + name or any(
                (job.get("Config", {}).get("Labels") or {}).get(k) != v for k, v in expected.items()
            ):
                return False
            self.output(["docker", "stop", "--time", "5", job["Id"]])
            checked = json.loads(self.output(["docker", "inspect", job["Id"]]))
            if len(checked) != 1 or checked[0]["State"]["Running"]:
                return False
            self.output(["docker", "rm", job["Id"]])
            if self.output(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"]).strip():
                return False
        return True

    def preflight(self):
        self.identity()
        if shutil.disk_usage(self.work).free < 2_147_483_648:
            raise ValueError("work_space_insufficient")
        if os.environ.get(
            "AVELREN_BACKUP_DB_USER", "avelren_backup"
        ) != "avelren_backup" or not os.environ.get("AVELREN_BACKUP_PASSWORD"):
            raise ValueError("backup_role_or_password_required")
        self.helper = os.environ.get("AVELREN_BACKUP_HELPER_IMAGE", "")
        self.helper_source = os.environ.get("AVELREN_BACKUP_HELPER_SOURCE_COMMIT", "")
        self.helper_hash = os.environ.get("AVELREN_BACKUP_HELPER_SHA256", "")
        if (
            not re.fullmatch(r"sha256:[0-9a-f]{64}", self.helper)
            or not re.fullmatch(r"[0-9a-f]{40}", self.helper_source)
            or not re.fullmatch(r"[0-9a-f]{64}", self.helper_hash)
        ):
            raise ValueError("pinned_helper_required")
        image = json.loads(self.output(["docker", "image", "inspect", self.helper]))
        if (
            len(image) != 1
            or image[0]["Id"] != self.helper
            or "AVELREN_GIT_SHA=" + self.helper_source not in image[0]["Config"].get("Env", [])
        ):
            raise ValueError("helper_source_mismatch")
        for variable in image[0]["Config"].get("Env", []):
            key, _, value = variable.partition("=")
            if value and re.search(r"DATABASE|(^|_)DB_|^PG|DSN|PASSWORD|SECRET|TOKEN", key):
                raise ValueError("helper_credentials_forbidden")
        code = (
            "import hashlib; import avelren.paired_backup_spool as m; "
            "print(hashlib.sha256(open(m.__file__, 'rb').read()).hexdigest())"
        )
        output = self.work / (".check-" + uuid.uuid4().hex)
        try:
            self.job(
                "check",
                self.helper,
                ["--network", "none", "--user", "10001:10001"],
                ["python", "-c", code],
                output,
            )
            if output.read_text().strip() != self.helper_hash:
                raise ValueError("helper_hash_mismatch")
        finally:
            output.unlink(missing_ok=True)
        if self.cancel_children([]) is not True:
            raise ValueError("children_unresolved")
        status = self.controller.execute(self.manifest, "preflight", ["--window-minutes", "15"])
        if status.get("max_cycle_bytes", 0) <= 0:
            raise ValueError("spool_preflight_denied")
        self.prepare_sql()

    def prepare_sql(self):
        if self.stack is None:
            raise ValueError("sql_context_required")
        configured = os.environ.get("AVELREN_BACKUP_COMPOSE_FILES")
        files = (
            configured.split(":")
            if configured
            else [
                str(self.stack / "docker-compose.yml"),
                str(self.stack / "docker-compose.override.yml"),
            ]
        )
        if not files or any(not Path(p).is_absolute() or not Path(p).is_file() for p in files):
            raise ValueError("sql_compose_files_required")
        self.controller.runtime.private_path(self.stack / ".env")
        for selected in files:
            path = Path(selected)
            for entry in (path, *path.parents):
                info = entry.lstat()
                if entry.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
                    raise ValueError("untrusted_sql_compose")
        # Existing deployments with a migration pin must explicitly select it.
        pin = Path("/var/lib/avelren-release-check-20260924/deploy-013.yml")
        if pin.exists() and str(pin) not in files:
            raise ValueError("sql_migration_pin_required")
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.stack),
            "--env-file",
            str(self.stack / ".env"),
            "-p",
            "avelren",
        ]
        for path in files:
            command.extend(["-f", path])
        env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
        effective = json.loads(self.output([*command, "config", "--format", "json"], env=env))
        ids = self.output([*command, "ps", "-q", "db"], env=env).split()
        if len(ids) != 1:
            raise ValueError("sql_database_identity_required")
        db = json.loads(self.output(["docker", "inspect", ids[0]]))[0]
        labels = db.get("Config", {}).get("Labels") or {}
        image = json.loads(
            self.output(["docker", "image", "inspect", effective["services"]["db"]["image"]])
        )[0]
        network = db["NetworkSettings"]["Networks"].get(self.manifest["network"])
        if (
            not db["State"]["Running"]
            or labels.get("com.docker.compose.project") != "avelren"
            or labels.get("com.docker.compose.service") != "db"
            or labels.get("com.docker.compose.project.config_files") != ",".join(files)
            or labels.get("com.docker.compose.project.working_dir") != str(self.stack)
            or image["Id"] != db["Image"]
            or network is None
        ):
            raise ValueError("sql_database_identity_mismatch")
        self.db_id, self.db_image = db["Id"], db["Image"]
        self.db_address = str(ipaddress.ip_address(network["IPAddress"]))

    def sql_snapshot(self, directory, backup_id, generation):
        before = json.loads(self.output(["docker", "inspect", self.db_id]))[0]
        if (
            not before["State"]["Running"]
            or before["Image"] != self.db_image
            or before["NetworkSettings"]["Networks"][self.manifest["network"]]["IPAddress"]
            != self.db_address
        ):
            raise ValueError("sql_database_changed")
        raw = directory / ".sql"
        self.job(
            "sql",
            self.db_image,
            ["--network", self.manifest["network"], "-e", "PGPASSWORD"],
            [
                "pg_dump",
                "--no-owner",
                "-U",
                "avelren_backup",
                "-d",
                "avelren",
                "-h",
                self.db_address,
            ],
            raw,
        )
        path = directory / f"avelren-{backup_id}.sql.gz"
        self.compress(raw, path)
        if path.stat().st_size < 10240:
            raise ValueError("sql_dump_too_small")
        return path

    def compress(self, source, destination):
        with source.open("rb") as original, destination.open("xb") as stream:
            os.chmod(destination, 0o600)
            with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as output:
                while chunk := original.read(1024 * 1024):
                    if time.monotonic() >= self.deadline:
                        raise ValueError("command_timeout")
                    output.write(chunk)
        source.unlink()

    def spool_snapshot(self, directory, backup_id, generation):
        output_dir = directory / ".spool-helper"
        output_dir.mkdir(mode=0o700)
        os.chown(output_dir, 10001, 10001)
        summary_file = directory / ".spool-summary"
        self.job(
            "spool",
            self.helper,
            [
                "--network",
                "none",
                "--user",
                "10001:10001",
                "--mount",
                "type=volume,src="
                + self.manifest["volume"]
                + ",dst=/var/lib/avelren/collector-spool",
                "--mount",
                "type=bind,src=" + str(output_dir) + ",dst=/output",
            ],
            [
                "python",
                "-m",
                "avelren.paired_backup_spool",
                "snapshot",
                "--source",
                "/var/lib/avelren/collector-spool/cycles.sqlite3",
                "--output",
                "/output/spool.sqlite3",
            ],
            summary_file,
        )
        raw = output_dir / "spool.sqlite3"
        if raw.is_symlink() or not stat.S_ISREG(raw.lstat().st_mode) or raw.stat().st_nlink != 1:
            raise ValueError("unsafe_helper_output")
        os.chown(raw, 0, 0)
        raw.chmod(0o600)
        os.chown(output_dir, 0, 0)
        summary = json.loads(summary_file.read_text())
        summary_file.unlink()
        path = directory / f"avelren-{backup_id}.spool.sqlite3.gz"
        self.compress(raw, path)
        output_dir.rmdir()
        return path, summary


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "recover"):
        child = commands.add_parser(command)
        child.add_argument(
            "--manifest",
            type=Path,
            default=Path(
                os.environ.get("AVELREN_RUNTIME_MANIFEST", "/etc/avelren/collector-runtime.json")
            ),
        )
        child.add_argument("--state-dir", type=Path)
        if command == "run":
            for name in ("work-dir", "stack-dir", "rclone-config", "receipt"):
                child.add_argument("--" + name, type=Path, required=True)
            child.add_argument("--remote", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        state.require_process_supervision()
        controller = load_controller()
        manifest = controller.runtime.load_manifest(args.manifest)
        state_dir = Path(manifest["state_dir"])
        if args.state_dir is not None and args.state_dir != state_dir:
            raise ValueError("state_manifest_mismatch")
        if args.command == "recover":
            runtime = Runtime(manifest, state_dir)
            with state.backup_lock(state_dir):
                current = state.read_state(state_dir)
                if current:
                    runtime.generation = current["generation"]
                result = state.recover_owned_run(state_dir, runtime=runtime)
                if (
                    result.get("phase") not in state.TERMINAL
                    and result.get("status") != "no_backup_state"
                ):
                    raise ValueError("backup_recovery_required")
                print(json.dumps({"status": "backup_recovery_complete"}))
            return 0
        args.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        private_directory(args.work_dir)
        runtime = Runtime(manifest, args.work_dir, args.stack_dir)
        publisher = Publisher(args.remote, args.rclone_config, args.work_dir)
        result = Coordinator(
            state_dir,
            args.work_dir,
            runtime,
            publisher,
            args.receipt,
            Path(os.environ.get("AVELREN_BACKUP_STAMP", "/run/avelren-backup.stamp")),
        ).run()
        print(json.dumps(result))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "failed", "reason": "cancelled"}))
        return 130
    except BackupError as error:
        print(json.dumps({"status": "failed", "reason": str(error)}))
        return 1
    except (ValueError, OSError, KeyError, TypeError, ImportError):
        print(json.dumps({"status": "failed", "reason": "paired_backup_failed"}))
        return 1


if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    raise SystemExit(main())
