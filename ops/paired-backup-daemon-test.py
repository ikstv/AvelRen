"""Real daemon/coordinator/Docker jobs; only upstream HTTP is synthetic."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = "avelren-app@sha256:9d32a0d54ff9711b54a082f39074e21ba456775b078caf01a293b95109674735"
RCLONE = "rclone/rclone@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5"
DEVICE = "11111111-1111-4111-8111-111111111111"
SPOOL = "/var/lib/avelren/collector-spool"
PLUGIN_HASH = "db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
FAILURE_LOG = Path("/evidence/paired-backup-failure.log")
OWNER_WRITER = None


def install_cancellation():
    def cancelled(signum, frame):
        raise KeyboardInterrupt("fixture_cancelled")

    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, cancelled)


def completed_cycle_after(value, completion):
    calls, status = value["calls"], value["status"]
    return bool(
        calls
        and calls[-1]["native_attempt_monotonic"] > completion
        and status["pending_count"] == 0
        and status["acked_count"] >= len(calls)
    )


def native_request_intervals(calls):
    starts = [call["native_attempt_monotonic"] for call in calls]
    if any(
        type(start) not in (int, float) or not math.isfinite(start)
        or call["monotonic"] < start
        for start, call in zip(starts, calls, strict=True)
    ):
        raise ValueError("invalid_native_request_trace")
    intervals = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    if any(interval < 60 for interval in intervals):
        raise ValueError("native_request_interval")
    return intervals


def registered_create(tracked, name, create):
    tracked.append(name)
    return create()


class Cleanup:
    """Bounded best effort: attempt every registered operation, preserve failures."""

    def __init__(self, *, seconds=150):
        self.deadline = time.monotonic() + seconds
        self.operations = []

    def add(self, name, operation):
        self.operations.append((name, operation))

    def run(self, argv, *, env=None):
        # Cleanup Docker clients get a short bounded reap period; the main
        # nested rehearsal command gets the longer graceful child cleanup.
        return command(
            argv,
            env=env,
            seconds=max(0.1, min(15, self.deadline - time.monotonic())),
            termination_seconds=0.2,
            reap_seconds=0.5,
        )

    def remove(self, kind, name, labels=None):
        ids = self.run(
            [
                "docker",
                kind,
                "ls",
                "--format",
                "{{.Names}}" if kind == "container" else "{{.Name}}",
                *(["-a"] if kind == "container" else []),
            ]
        )
        if name not in ids.splitlines():
            return
        item = json.loads(self.run(["docker", kind, "inspect", name]))[0]
        actual = (
            item.get("Config", {}).get("Labels", {})
            if kind == "container"
            else item.get("Labels", {})
        )
        if labels and any((actual or {}).get(key) != value for key, value in labels.items()):
            raise ValueError("cleanup_ownership_unproven")
        options = ["-fv"] if kind == "container" else []
        self.run(["docker", kind, "rm", *options, name])

    def finish(self):
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, signal.SIG_IGN)
        errors = []
        for name, operation in self.operations:
            try:
                operation()
            except BaseException as error:
                errors.append(name + ":" + type(error).__name__)
        return errors


def command(argv, *, env=None, seconds=180, termination_seconds=45, reap_seconds=5):
    if OWNER_WRITER is not None:
        OWNER_WRITER()
    process = subprocess.Popen(
        argv,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except BaseException:
        handlers = {
            s: signal.signal(s, signal.SIG_IGN)
            for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
        }
        try:
            # poll=None proves this exact unreaped child is still alive. Never
            # signal a stored numeric group after its leader has been reaped.
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.communicate(timeout=termination_seconds)
                except subprocess.TimeoutExpired:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=reap_seconds)
        except BaseException:
            pass  # Keep the original timeout/cancellation and durable ledger.
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
        raise
    if process.returncode:
        # Synthetic fixture only; keep raw diagnostics in private evidence.
        if not FAILURE_LOG.exists():
            FAILURE_LOG.write_text(stdout + stderr)
        raise AssertionError("fixture_command_failed:" + argv[0])
    return stdout


def wait(predicate, seconds=40):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError("fixture_condition_timeout")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_ledger(value, prefix):
    if not re.fullmatch(r"avelren-runtime-test-pair-[0-9]+-[0-9]+", prefix):
        raise ValueError("invalid_fixture_prefix")
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "format_version",
            "fixture",
            "containers",
            "images",
            "created_volume",
            "created_network",
            "sql_started",
        }
        or type(value["format_version"]) is not int
        or value["format_version"] != 1
        or value["fixture"] != prefix
    ):
        raise ValueError("invalid_fixture_ledger")
    for flag in ("created_volume", "created_network", "sql_started"):
        if type(value[flag]) is not bool:
            raise ValueError("invalid_fixture_ledger")
    for key, suffixes in (
        ("containers", ("collector", "api", "rclone", "sql-lock")),
        ("images", ("offline-base", "helper", "collector-image")),
    ):
        if (
            not isinstance(value[key], list)
            or len(value[key]) > len(suffixes)
            or any(
                name not in {prefix + "-" + suffix for suffix in suffixes} for name in value[key]
            )
        ):
            raise ValueError("invalid_fixture_ledger")
        if len(set(value[key])) != len(value[key]):
            raise ValueError("invalid_fixture_ledger")


def write_ledger(fixture, value):
    validate_ledger(value, value["fixture"])
    write_private_json(fixture / "owned.json", value)


def write_private_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".fixture-journal-", dir=path.parent)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_private_json(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o077
        or info.st_nlink != 1
        or info.st_size > 65536
    ):
        raise ValueError("untrusted_fixture_journal")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_fixture_journal_key")
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


def validate_job_owners(value, prefix):
    if not isinstance(value, list) or len(value) > 2:
        raise ValueError("invalid_job_owners")
    generations = set()
    for owner in value:
        if (
            not isinstance(owner, dict)
            or set(owner) != {"generation", "identity"}
            or not isinstance(owner["generation"], str)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", owner["generation"])
            or owner["generation"] in generations
        ):
            raise ValueError("invalid_job_owners")
        generations.add(owner["generation"])
        identity = owner["identity"]
        if (
            not isinstance(identity, dict)
            or set(identity)
            != {
                "container_id",
                "image_id",
                "source_commit",
                "restart_count",
                "started_at",
                "volume",
                "network",
            }
            or identity["volume"] != prefix + "-spool"
            or identity["network"] != prefix + "-network"
            or type(identity["restart_count"]) is not int
            or identity["restart_count"] < 0
            or not isinstance(identity["started_at"], str)
            or len(identity["started_at"]) > 64
        ):
            raise ValueError("invalid_job_identity")
        for key, pattern in (
            ("container_id", r"[0-9a-f]{64}"),
            ("image_id", r"sha256:[0-9a-f]{64}"),
            ("source_commit", r"[0-9a-f]{40}"),
        ):
            if not isinstance(identity[key], str) or not re.fullmatch(pattern, identity[key]):
                raise ValueError("invalid_job_identity")


def register_job_owner(fixture, prefix, generation, identity):
    path = fixture / "job-owners.json"
    owners = read_private_json(path) if path.exists() else []
    owner = dict(generation=generation, identity=identity)
    if owner not in owners:
        owners.append(owner)
    validate_job_owners(owners, prefix)
    write_private_json(path, owners)


def cleanup_only(args):
    os.umask(0o077)
    fixture, prefix = args.fixture.resolve(), args.prefix
    assert fixture.name == "_data" and fixture.parent.name == prefix + "-controller-data"
    assert not args.fixture.is_symlink()
    value = read_private_json(fixture / "owned.json")
    validate_ledger(value, prefix)
    info = (fixture / "owned.json").lstat()
    assert info.st_uid == 0 and info.st_mode & 0o077 == 0 and info.st_nlink == 1
    volume = json.loads(command(["docker", "volume", "inspect", prefix + "-controller-data"]))[0]
    assert volume["Labels"].get("org.avelren.test.fixture") == prefix
    client = Path("/etc/avelren/docker-client/cli-plugins")
    client.mkdir(parents=True, mode=0o700)
    shutil.copy("/usr/local/libexec/docker/cli-plugins/docker-compose", client / "docker-compose")
    (client / "docker-compose").chmod(0o755)
    assert hashlib.sha256((client / "docker-compose").read_bytes()).hexdigest() == PLUGIN_HASH
    os.environ["DOCKER_CONFIG"] = str(client.parent)
    original = (
        json.loads((fixture / "cleanup.json").read_text())
        if (fixture / "cleanup.json").exists()
        else None
    )
    result = cleanup_fixture(fixture, prefix, value, first_failure="outer_recovery")
    result["original_receipt"] = original
    (fixture / "cleanup.json").write_text(json.dumps(result))
    Path("/evidence/paired-backup-cleanup-" + prefix + ".json").write_text(json.dumps(result))
    print(json.dumps(result))
    return 1 if result["errors"] else 0


def cleanup_fixture(fixture, prefix, ledger, *, coordinator_pid=None, first_failure=None):
    validate_ledger(ledger, prefix)
    sys.path.insert(0, str(fixture / "source/ops"))

    containers, images = ledger["containers"], ledger["images"]
    created_volume, created_network, sql_started = (
        ledger[k] for k in ("created_volume", "created_network", "sql_started")
    )
    volume, network, sql_project = prefix + "-spool", prefix + "-network", prefix + "-sql"
    stack = fixture / "stack"
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(stack),
        "--env-file",
        str(stack / ".env"),
        "-p",
        sql_project,
        "-f",
        str(stack / "docker-compose.yml"),
    ]
    environment = dict(os.environ)
    cleanup = Cleanup()

    def stop_coordinator():
        if coordinator_pid:
            try:
                finished, _ = os.waitpid(coordinator_pid, os.WNOHANG)
            except ChildProcessError:
                return
            if finished:
                return
            # A live unreaped own child cannot have its numeric PID reused.
            os.kill(coordinator_pid, signal.SIGKILL)
            deadline = time.monotonic() + 10
            while not os.waitpid(coordinator_pid, os.WNOHANG)[0]:
                if time.monotonic() >= deadline:
                    raise TimeoutError("coordinator_reap_timeout")
                time.sleep(0.1)

    cleanup.add("coordinator", stop_coordinator)

    def remove_job(kind):
        path = fixture / "job-owners.json"
        owners = read_private_json(path) if path.exists() else []
        validate_job_owners(owners, prefix)
        failures = []
        for current in owners:
            name = "avelren-paired-" + current["generation"] + "-" + kind
            runtime_hash = hashlib.sha256(
                json.dumps(current["identity"], sort_keys=True).encode()
            ).hexdigest()
            try:
                cleanup.remove(
                    "container",
                    name,
                    {
                        "org.avelren.backup.generation": current["generation"],
                        "org.avelren.backup.runtime": runtime_hash,
                    },
                )
            except BaseException as error:
                failures.append(type(error).__name__)
        if failures:
            raise ValueError("cleanup_job_removals_unproven:" + ",".join(failures))

    for kind in ("check", "sql", "spool", "control-on", "control-off"):
        cleanup.add("job-" + kind, lambda kind=kind: remove_job(kind))
    for name in reversed(containers):
        labels = (
            {"com.docker.compose.project": prefix}
            if name.endswith("-collector")
            else {"org.avelren.test.fixture": prefix}
        )
        cleanup.add(
            name, lambda name=name, labels=labels: cleanup.remove("container", name, labels)
        )
    for directory in fixture.glob("avelren-paired-restore.*"):
        cleanup.add(
            "nested-" + directory.name,
            lambda directory=directory: cleanup_nested_restore(fixture, directory, cleanup),
        )
    if sql_started:
        cleanup.add(
            "sql-compose",
            lambda: cleanup.run(
                [*compose, "down", "--volumes", "--remove-orphans"], env=environment
            ),
        )
        sql_labels = {"com.docker.compose.project": sql_project}
        cleanup.add(
            "sql-container-fallback",
            lambda: cleanup.remove("container", sql_project + "-db-1", sql_labels),
        )
        cleanup.add(
            "sql-volume-fallback",
            lambda: cleanup.remove("volume", sql_project + "_db_data", sql_labels),
        )
    for kind, name, created in (
        ("volume", volume, created_volume),
        ("network", network, created_network),
    ):
        if created:
            cleanup.add(
                name,
                lambda kind=kind, name=name: cleanup.remove(
                    kind, name, {"org.avelren.test.fixture": prefix}
                ),
            )

    def remove_image(tag):
        tags = cleanup.run(["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"])
        if tag + ":latest" in tags.splitlines():
            cleanup.run(["docker", "image", "rm", tag])

    for tag in reversed(images):
        cleanup.add(tag, lambda tag=tag: remove_image(tag))
    errors = cleanup.finish()
    cleanup_receipt = dict(
        format_version=1,
        fixture=prefix,
        status="FAIL" if errors else "PASS",
        errors=errors,
        first_failure=first_failure,
    )
    (fixture / "cleanup.json").write_text(json.dumps(cleanup_receipt))
    Path("/evidence/paired-backup-cleanup-" + prefix + ".json").write_text(
        json.dumps(cleanup_receipt)
    )
    return cleanup_receipt


def cleanup_nested_restore(fixture, directory, cleanup):
    value = read_private_json(directory / "project.json")
    if (
        set(value)
        != {"format_version", "project", "compose_file", "working_dir", "env_file", "app_image"}
        or type(value["format_version"]) is not int
        or value["format_version"] != 1
        or directory.is_symlink()
        or directory.parent != fixture
        or not re.fullmatch(r"avelren-paired-restore\.[A-Za-z0-9]{8}", directory.name)
        or value["working_dir"] != str(directory)
        or value["env_file"] != str(directory / "compose.env")
        or value["compose_file"] != str(fixture / "source/ops/compose.paired-restore-test.yml")
        or not re.fullmatch(r"avelren-paired-restore-[0-9]+-[0-9]+-[0-9]+", value["project"])
        or not (
            re.fullmatch(r"sha256:[0-9a-f]{64}", value["app_image"]) or value["app_image"] == APP
        )
    ):
        raise ValueError("invalid_nested_restore_journal")
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("untrusted_nested_restore_owner")
    ids = cleanup.run(
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + value["project"]]
    ).split()
    app_id = json.loads(cleanup.run(["docker", "image", "inspect", value["app_image"]]))[0]["Id"]
    db_id = json.loads(
        cleanup.run(
            [
                "docker",
                "image",
                "inspect",
                "timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9",
            ]
        )
    )[0]["Id"]
    for identifier in ids:
        item = json.loads(cleanup.run(["docker", "inspect", identifier]))[0]
        labels = item["Config"].get("Labels") or {}
        service = labels.get("com.docker.compose.service")
        if (
            service not in {"db", "test"}
            or labels.get("com.docker.compose.project.config_files") != value["compose_file"]
            or labels.get("com.docker.compose.project.working_dir") != value["working_dir"]
            or item["Image"] != (db_id if service == "db" else app_id)
        ):
            raise ValueError("nested_restore_ownership_unproven")
    nested = Cleanup(seconds=max(0.1, cleanup.deadline - time.monotonic()))
    for identifier in ids:
        nested.add(
            identifier,
            lambda identifier=identifier: nested.run(["docker", "rm", "-fv", identifier]),
        )
    for kind, name in (
        ("volume", value["project"] + "_db_data"),
        ("network", value["project"] + "_isolated"),
    ):
        nested.add(
            name,
            lambda kind=kind, name=name: nested.remove(
                kind, name, {"com.docker.compose.project": value["project"]}
            ),
        )
    errors = nested.finish()
    if errors:
        raise ValueError("nested_restore_cleanup_failed")
    shutil.rmtree(directory)  # Validated private own direct child, never caller-selected.


def run(args):
    global FAILURE_LOG, OWNER_WRITER
    os.umask(0o077)
    install_cancellation()
    assert re.fullmatch(r"[0-9a-f]{40}", args.source_commit)
    assert re.fullmatch(r"avelren-runtime-test-pair-[0-9]+-[0-9]+", args.prefix)
    FAILURE_LOG = Path("/evidence/paired-backup-failure-" + args.prefix + ".log")
    fixture = args.fixture.resolve()
    assert fixture.name == "_data" and fixture.parent.name == args.prefix + "-controller-data"
    fixture.chmod(0o700)
    root = fixture / "source"
    root.mkdir(mode=0o755)
    for name in ("ops", "db", "services"):
        shutil.copytree(Path("/work") / name, root / name)
    for directory, _, files in os.walk(root):
        Path(directory).chmod(0o755)
        for name in files:
            (Path(directory) / name).chmod(0o644)
    sys.path.insert(0, str(root / "ops"))
    paired = load(root / "ops/paired-backup.py", "paired")
    old = load(root / "ops/collector-runtime-daemon-test.py", "old_fixture")
    state = paired.state
    containers, images = [], []
    network, volume = args.prefix + "-network", args.prefix + "-spool"
    sql_project = args.prefix + "-sql"
    stack = fixture / "stack"
    stack.mkdir(mode=0o700)
    compose_file = stack / "docker-compose.yml"
    shutil.copy(root / "ops/compose.paired-backup-test.yml", compose_file)
    compose_file.chmod(0o600)
    (stack / ".env").write_text("PAIRED_TEST_NETWORK=" + network + "\n")
    (stack / ".env").chmod(0o600)
    compose = [
        "docker",
        "compose",
        "--project-directory",
        str(stack),
        "--env-file",
        str(stack / ".env"),
        "-p",
        sql_project,
        "-f",
        str(compose_file),
    ]
    environment = dict(os.environ)
    evidence = dict(
        source_commit=args.source_commit, source_kind="working_tree_fixture", project=args.prefix
    )
    coordinator_pid = None
    first_failure = None
    created_volume = created_network = sql_started = False

    def ownership():
        return dict(
            format_version=1,
            fixture=args.prefix,
            containers=list(containers),
            images=list(images),
            created_volume=created_volume,
            created_network=created_network,
            sql_started=sql_started,
        )

    def persist_ownership():
        write_ledger(fixture, ownership())

    OWNER_WRITER = persist_ownership
    OWNER_WRITER()
    try:
        assert not command(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + sql_project]
        ).strip()
        names = command(["docker", "ps", "-a", "--format", "{{.Names}}"])
        assert all(
            name == args.prefix + "-controller" or not name.startswith(args.prefix)
            for name in names.splitlines()
        )
        for kind, permitted in (("volume", args.prefix + "-controller-data"), ("network", None)):
            names = command(["docker", kind, "ls", "--format", "{{.Name}}"])
            assert all(
                name == permitted or not name.startswith(args.prefix) for name in names.splitlines()
            )
        print("build offline installed helper and synthetic transport image", flush=True)
        build = fixture / "build"
        build.mkdir()
        base_tag = args.prefix + "-offline-base"
        images.append(base_tag)
        if args.local_base:
            command(["docker", "tag", APP, base_tag])
        else:
            command(
                [
                    "docker",
                    "build",
                    "--build-arg",
                    "SOURCE_COMMIT=" + args.source_commit,
                    "-t",
                    base_tag,
                    str(root / "services/backend"),
                ],
                seconds=600,
            )
        shutil.copytree(root / "services/backend/src/avelren", build / "avelren")
        shutil.copytree(root / "db", build / "db")
        shutil.copy(root / "ops/collector-spool-daemon-test.py", build / "seed.py")
        # Install the current complete package at the existing pinned app's actual
        # site-packages location, offline. No mounted source/PYTHONPATH proof.
        (build / "Dockerfile").write_text(
            f"FROM {base_tag}\nUSER root\n"
            "COPY avelren /usr/local/lib/python3.14/site-packages/avelren\n"
            "COPY db /fixture/db\nCOPY seed.py /fixture/seed.py\n"
            f"ENV AVELREN_GIT_SHA={args.source_commit}\nUSER 10001:10001\n"
        )
        helper_tag = args.prefix + "-helper"
        images.append(helper_tag)
        command(["docker", "build", "--network", "none", "-t", helper_tag, str(build)], seconds=600)
        helper = json.loads(command(["docker", "image", "inspect", helper_tag]))[0]["Id"]
        proof = json.loads(
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    helper,
                    "python",
                    "-c",
                    "import json,os,hashlib;import avelren.paired_backup_spool as m;"
                    "from avelren import collector_control as c;"
                    "print(json.dumps(dict(uid=os.geteuid(),origin=m.__file__,"
                    "sha256=hashlib.sha256(open(m.__file__,'rb').read()).hexdigest(),"
                    "control_origin=c.__file__,"
                    "control_sha256=hashlib.sha256(open(c.__file__,'rb').read()).hexdigest())))",
                ]
            )
        )
        assert proof["uid"] == 10001
        assert (
            proof["origin"]
            == "/usr/local/lib/python3.14/site-packages/avelren/paired_backup_spool.py"
        )
        assert (
            proof["sha256"]
            == hashlib.sha256((build / "avelren/paired_backup_spool.py").read_bytes()).hexdigest()
        )
        assert proof["control_origin"] == (
            "/usr/local/lib/python3.14/site-packages/avelren/collector_control.py"
        )
        assert proof["control_sha256"] == hashlib.sha256(
            (build / "avelren/collector_control.py").read_bytes()
        ).hexdigest()
        evidence.update(helper_image_id=helper, installed_helper=proof)
        transport = old.SYNTHETIC.replace(
            "    original=httpx.AsyncClient",
            "    from avelren.echerha import RequestPacer\n"
            "    attempts=[]\n"
            "    original_wait=RequestPacer.wait\n"
            "    async def observed_wait(self):\n"
            "        await original_wait(self)\n"
            "        attempts.append(self.last_start)\n"
            "    RequestPacer.wait=observed_wait\n"
            "    original=httpx.AsyncClient",
        ).replace(
            "        trace=Path(",
            "        assert len(attempts)==1\n"
            "        native_attempt=attempts.pop(0)\n"
            "        trace=Path(",
        ).replace(
            "{'at':time.time()}",
            "{'at':time.time(),'monotonic':time.monotonic(),"
            "'native_attempt_monotonic':native_attempt,"
            "'device':request.headers['X-Device-Id']}",
        )
        (build / "sitecustomize.py").write_text(transport)
        (build / "sitecustomize.py").chmod(0o644)
        (build / "Dockerfile.collector").write_text(
            f"FROM {helper_tag}\nCOPY sitecustomize.py /synthetic/sitecustomize.py\n"
            "ENV PYTHONPATH=/synthetic AVELREN_RUNTIME_TEST_SYNTHETIC=1\n"
        )
        collector_tag = args.prefix + "-collector-image"
        images.append(collector_tag)
        command(
            [
                "docker",
                "build",
                "--network",
                "none",
                "-f",
                str(build / "Dockerfile.collector"),
                "-t",
                collector_tag,
                str(build),
            ]
        )
        image = json.loads(command(["docker", "image", "inspect", collector_tag]))[0]["Id"]
        evidence["collector_image_id"] = image
        rclone_container = args.prefix + "-rclone"
        containers.append(rclone_container)
        command(
            [
                "docker",
                "create",
                "--name",
                rclone_container,
                "--label",
                "org.avelren.test.fixture=" + args.prefix,
                "--network",
                "none",
                RCLONE,
            ]
        )
        command(
            ["docker", "cp", rclone_container + ":/usr/local/bin/rclone", "/usr/local/bin/rclone"]
        )
        command(["docker", "rm", rclone_container])
        containers.remove(rclone_container)
        client = Path("/etc/avelren/docker-client/cli-plugins")
        client.mkdir(parents=True, mode=0o700)
        client.parent.chmod(0o700)
        shutil.copy(
            "/usr/local/libexec/docker/cli-plugins/docker-compose", client / "docker-compose"
        )
        (client / "docker-compose").chmod(0o755)
        assert paired.digest(client / "docker-compose") == PLUGIN_HASH
        environment.update(DOCKER_CONFIG=str(client.parent))
        os.environ.update(
            DOCKER_CONFIG=str(client.parent),
            AVELREN_BACKUP_COMPOSE_SHA256=PLUGIN_HASH,
            AVELREN_BACKUP_PASSWORD="ci-only",
            AVELREN_BACKUP_HELPER_IMAGE=helper,
            AVELREN_BACKUP_HELPER_SOURCE_COMMIT=args.source_commit,
            AVELREN_BACKUP_HELPER_SHA256=proof["sha256"],
            AVELREN_BACKUP_COMPOSE_FILES=str(compose_file),
        )
        created_network = True
        command(
            [
                "docker",
                "network",
                "create",
                "--label",
                "org.avelren.test.fixture=" + args.prefix,
                "--internal",
                network,
            ]
        )
        created_volume = True
        command(
            [
                "docker",
                "volume",
                "create",
                "--label",
                "org.avelren.test.fixture=" + args.prefix,
                volume,
            ]
        )
        sql_started = True
        command([*compose, "up", "-d", "--pull", "never", "db"], env=environment)
        db = command([*compose, "ps", "-q", "db"], env=environment).strip()
        wait(
            lambda: (
                subprocess.run(
                    ["docker", "exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "avelren_admin"],
                    capture_output=True,
                ).returncode
                == 0
            )
        )
        command(["docker", "cp", str(root / "ops"), db + ":/tmp/ops"])
        command(["docker", "cp", str(root / "db"), db + ":/tmp/db"])
        bootstrap = [
            "docker",
            "exec",
            "-e",
            "AVELREN_TEST_DB=1",
            "-e",
            "AVELREN_DB_NAME=avelren",
            "-e",
            "AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres",
        ]
        for role in ("ADMIN", "MIGRATOR", "BACKUP", "COLLECTOR", "NOTIFIER", "WATCHDOG", "API"):
            bootstrap.extend(["-e", "AVELREN_" + role + "_PASSWORD=ci-only"])
        command([*bootstrap, db, "bash", "/tmp/ops/postgres-bootstrap.sh", "fresh"])

        def dsn(role):
            return "postgresql://" + role + ":ci-only@paired-db:5432/avelren"

        command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "-e",
                "DATABASE_URL=" + dsn("avelren_migrator"),
                helper,
                "python",
                "-m",
                "avelren.migrate",
                "/fixture/db/migrations",
            ]
        )
        command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                network,
                "-e",
                "DATABASE_URL=" + dsn("avelren_admin"),
                "-e",
                "ECHERHA_DEVICE_ID=" + DEVICE,
                helper,
                "python",
                "/fixture/seed.py",
                "seed",
            ]
        )
        command(
            [
                "docker",
                "exec",
                db,
                "psql",
                "-U",
                "avelren_admin",
                "-d",
                "avelren",
                "-c",
                "DROP TRIGGER spool_test_order ON collector_runs; "
                "DROP FUNCTION spool_record_order(); DROP TABLE spool_replay_order;",
            ]
        )
        command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "0",
                "-v",
                volume + ":" + SPOOL,
                helper,
                "python",
                "-c",
                f"import os;os.chown('{SPOOL}',10001,10001);os.chmod('{SPOOL}',0o700)",
            ]
        )
        env_file = fixture / "collector.env"
        env_file.write_text(
            "DATABASE_URL="
            + dsn("avelren_collector")
            + "\nECHERHA_DEVICE_ID="
            + DEVICE
            + "\nECHERHA_DEVICE_NAME=Synthetic paired collector\n"
        )
        env_file.chmod(0o600)
        state_dir, work = fixture / "state", fixture / "work"
        state_dir.mkdir(mode=0o700)
        work.mkdir(mode=0o700)
        manifest = dict(
            source_commit=args.source_commit,
            image_id=image,
            env_file=str(env_file),
            compose_file=str(root / "ops/compose.collector-runtime.yml"),
            project=args.prefix,
            container_name=args.prefix + "-collector",
            network=network,
            volume=volume,
            state_dir=str(state_dir),
        )
        manifest_path = fixture / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        manifest_path.chmod(0o600)
        collector_env = dict(
            environment,
            COLLECTOR_IMAGE_ID=image,
            COLLECTOR_ENV_FILE=str(env_file),
            COLLECTOR_CONTAINER_NAME=manifest["container_name"],
            COLLECTOR_NETWORK=network,
            COLLECTOR_VOLUME=volume,
        )
        collector_compose = [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-p",
            args.prefix,
            "-f",
            manifest["compose_file"],
        ]
        registered_create(
            containers,
            manifest["container_name"],
            lambda: command(
                [*collector_compose, "up", "-d", "--no-build", "--pull", "never", "collector"],
                env=collector_env,
            ),
        )
        api = args.prefix + "-api"
        containers.append(api)
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                api,
                "--label",
                "org.avelren.test.fixture=" + args.prefix,
                "--network",
                network,
                "-e",
                "DATABASE_URL=" + dsn("avelren_api"),
                helper,
                "uvicorn",
                "avelren.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8080",
            ]
        )

        def smoke():
            command(
                [
                    "docker",
                    "exec",
                    api,
                    "python",
                    "-c",
                    "import urllib.request;assert urllib.request.urlopen('http://127.0.0.1:8080/checkpoints').status==200",
                ]
            )

        def status():
            return json.loads(
                command(["docker", "exec", manifest["container_name"], "python", "-c", old.CHECK])
            )

        def runtime():
            return ObservedRuntime.for_disposable(
                manifest_path, work, stack, sql_project=sql_project
            )

        class ObservedRuntime(paired.Runtime):
            # Observation after the actual native snapshot, before Coordinator
            # removes its job. No operation/result/authority is replaced.
            def job(self, kind, image, options, command, output):
                # Independent fixture cleanup also retains exact owned jobs.
                register_job_owner(fixture, args.prefix, self.generation, self.identity())
                try:
                    return super().job(kind, image, options, command, output)
                except BaseException:
                    logs = subprocess.run(
                        ["docker", "logs", self.job_name(kind)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    Path("/evidence/paired-backup-job-error.log").write_text(
                        logs.stdout + logs.stderr
                    )
                    raise

            def event(self, name):
                with (fixture / "lifecycle.jsonl").open("a") as stream:
                    stream.write(
                        json.dumps(
                            dict(event=name, generation=self.generation, monotonic=time.monotonic())
                        )
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())

            def capture_only(self, mode, authority):
                if mode == "off":
                    for kind in ("check", "sql", "spool", "control-on", "control-off"):
                        assert not self.output(
                            [
                                "docker",
                                "ps",
                                "-aq",
                                "--filter",
                                "name=^/" + self.job_name(kind) + "$",
                            ]
                        ).strip()
                    self.event("owned_jobs_absent_before_off")
                result = super().capture_only(mode, authority)
                assert result["mode_ack"] is (mode == "on")
                self.event(mode + "_ack")
                return result

            def sql_snapshot(self, directory, backup_id, generation):
                result = super().sql_snapshot(directory, backup_id, generation)
                self.event("sql_snapshot_complete")
                return result

            def spool_snapshot(self, directory, backup_id, generation):
                result = super().spool_snapshot(directory, backup_id, generation)
                job = json.loads(self.output(["docker", "inspect", self.job_name("spool")]))[0]
                assert job["Config"]["User"] == "10001:10001"
                assert job["HostConfig"]["NetworkMode"] == "none"
                mounts = {mount["Destination"]: mount for mount in job["Mounts"]}
                assert mounts[SPOOL]["Type"] == "volume" and mounts[SPOOL]["Name"] == volume
                assert mounts["/output"]["Type"] == "bind"
                assert mounts["/output"]["Source"] == str(directory / ".spool-helper")
                proof = dict(
                    uid=10001,
                    network="none",
                    live_volume=volume,
                    output_bind=mounts["/output"]["Source"],
                    image_id=job["Image"],
                )
                (fixture / "helper-bind-proof.json").write_text(json.dumps(proof))
                self.event("spool_snapshot_complete")
                return result

        remote_dir = fixture / "encrypted"
        remote_dir.mkdir(mode=0o700)
        password = command(["rclone", "obscure", "fixture-only-password"]).strip()
        config = fixture / "rclone.conf"
        config.write_text(
            f"[crypt]\ntype = crypt\nremote = {remote_dir}\npassword = {password}\n"
            "filename_encryption = standard\n"
        )
        config.chmod(0o600)
        receipt, stamp = fixture / "receipt", fixture / "stamp"
        stamp.write_text("old-stamp\n")
        stamp.chmod(0o600)

        def start_coordinator():
            nonlocal coordinator_pid
            coordinator_pid = os.fork()
            if coordinator_pid == 0:
                try:
                    paired.Coordinator(
                        state_dir,
                        work,
                        runtime(),
                        paired.Publisher("crypt:paired", config, work),
                        receipt,
                        stamp,
                    ).run()
                    os._exit(0)
                except BaseException:
                    import traceback

                    Path("/evidence/paired-backup-driver-error.log").write_text(
                        traceback.format_exc()
                    )
                    os._exit(1)

        def lock_sql():
            name = args.prefix + "-sql-lock"
            containers.append(name)
            command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--label",
                    "org.avelren.test.fixture=" + args.prefix,
                    "--network",
                    network,
                    "-e",
                    "PGPASSWORD=ci-only",
                    "-e",
                    "PGAPPNAME=" + name,
                    "--entrypoint",
                    "psql",
                    "timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9",
                    "-h",
                    "paired-db",
                    "-U",
                    "avelren_admin",
                    "-d",
                    "avelren",
                    "-c",
                    "BEGIN; LOCK TABLE observations IN ACCESS EXCLUSIVE MODE; "
                    "SELECT pg_sleep(300);",
                ]
            )
            wait(
                lambda: (
                    "1"
                    in command(
                        [
                            "docker",
                            "exec",
                            db,
                            "psql",
                            "-U",
                            "avelren_admin",
                            "-d",
                            "avelren",
                            "-Atc",
                            "SELECT count(*) FROM pg_locks l "
                            "JOIN pg_stat_activity a ON l.pid=a.pid "
                            "WHERE relation='observations'::regclass "
                            "AND mode='AccessExclusiveLock' AND granted AND a.application_name='"
                            + name
                            + "'",
                        ]
                    )
                )
            )
            return name

        def unlock(name):
            terminated = command(
                [
                    "docker",
                    "exec",
                    db,
                    "psql",
                    "-U",
                    "avelren_admin",
                    "-d",
                    "avelren",
                    "-Atc",
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE application_name='" + name + "' AND pid<>pg_backend_pid()",
                ]
            ).strip()
            assert terminated == "t"
            command(["docker", "rm", "-f", name])
            containers.remove(name)

        def owned_job():
            value = state.read_state(state_dir)
            if not value or value["phase"] != "paused":
                return False
            name = "avelren-paired-" + value["generation"] + "-sql"
            ids = command(["docker", "ps", "-q", "--filter", "name=^/" + name + "$"]).split()
            return ids[0] if ids else False

        print("wait first real producer cycle / API smoke", flush=True)
        wait(lambda: status()["status"]["acked_count"] >= 1 and status()["calls"], 90)
        smoke()
        first = status()["calls"][0]["at"]
        print("SIGKILL coordinator with actual running owned dump; recover", flush=True)
        locker = lock_sql()
        start_coordinator()
        wait(owned_job, 60)
        job_id = owned_job()
        assert status()["status"]["mode_ack"] is True
        smoke()
        os.kill(coordinator_pid, signal.SIGKILL)
        os.waitpid(coordinator_pid, 0)
        coordinator_pid = None
        assert status()["status"]["mode_ack"] is True
        assert json.loads(command(["docker", "inspect", job_id]))[0]["State"]["Running"]
        recovery = runtime()
        with state.backup_lock(state_dir):
            recovery.generation = state.read_state(state_dir)["generation"]
            recovery.verify_client()
            recovered = state.recover_owned_run(state_dir, runtime=recovery)
        assert recovered["phase"] == "resumed"
        assert not command(["docker", "ps", "-aq", "--filter", "id=" + job_id]).strip()
        assert status()["status"]["mode_ack"] is False
        assert stamp.read_text() == "old-stamp\n" and not receipt.exists()
        unlock(locker)
        wait(lambda: status()["status"]["pending_count"] == 0)
        evidence["sigkill_owned_job_terminated_before_off_ack"] = True
        print(
            "real backup: ACK -> blocked SQL -> next 60s capture -> copies -> off/drain", flush=True
        )
        locker = lock_sql()
        start_coordinator()
        wait(owned_job, 60)
        wait(lambda: len(status()["calls"]) >= 2 and status()["status"]["pending_count"] >= 1, 90)
        during = status()["calls"][-1]["at"]
        assert status()["status"]["mode_ack"] is True
        smoke()
        unlock(locker)
        _, exit_status = os.waitpid(coordinator_pid, 0)
        coordinator_pid = None
        assert os.waitstatus_to_exitcode(exit_status) == 0
        completion = time.monotonic()
        result = json.loads(receipt.read_text())
        assert result["writer_resumed"] and result["state_counts"]["pending"] >= 1
        assert [s["stage"] for s in result["writer_status"]] == [
            "resumed",
            "before_manifest",
            "published",
        ]
        assert all(
            s["pending_count"] == 0 and s["capture_only"] is False and s["mode_ack"] is False
            for s in result["writer_status"]
        )
        wait(lambda: completed_cycle_after(status(), completion), 90)
        after_call = status()["calls"][-1]
        after = after_call["at"]
        assert after_call["native_attempt_monotonic"] > completion
        smoke()
        assert first < during < after
        calls = status()["calls"]
        transport_intervals = [
            b["monotonic"] - a["monotonic"] for a, b in zip(calls, calls[1:], strict=False)
        ]
        intervals = native_request_intervals(calls)
        assert all(call["device"] == DEVICE for call in calls)
        evidence.update(
            cycles_before_during_after=len(calls),
            start_intervals_seconds=intervals,
            start_measurement="original RequestPacer.wait self.last_start before client.send",
            request_attempts=calls,
            transport_intervals_seconds=transport_intervals,
            api_smoke_before_during_after=True,
            writer_receipt=result,
            producer_boundary_events=dict(before=first, during=during, after=after),
            backup_completion_monotonic=completion,
            after_start_monotonic=after_call["native_attempt_monotonic"],
        )
        evidence["native_helper_bind_proof"] = json.loads(
            (fixture / "helper-bind-proof.json").read_text()
        )
        print("native restart/drain with persistent ID", flush=True)
        owned = runtime()
        owned.controller.execute(manifest, "restart", [])
        wait(
            lambda: (
                len(status()["calls"]) > len(calls) and status()["status"]["pending_count"] == 0
            ),
            90,
        )
        inspection = json.loads(command(["docker", "inspect", manifest["container_name"]]))[0]
        assert "ECHERHA_DEVICE_ID=" + DEVICE in inspection["Config"]["Env"]
        final_calls = status()["calls"]
        evidence["restart_start_intervals_seconds"] = native_request_intervals(final_calls)
        assert all(call["device"] == DEVICE for call in final_calls)
        owned.identity()  # Scans full inventory and rejects a second producer.
        evidence["restart_persistent_id_drain_single_producer"] = True
        download = fixture / "download"
        download.mkdir(mode=0o700)
        command(
            [
                "rclone",
                "copy",
                "crypt:paired/"
                + (
                    "daily"
                    if "/daily/" in result["remote_paths"][0]
                    else "weekly"
                    if "/weekly/" in result["remote_paths"][0]
                    else "monthly"
                ),
                str(download),
                "--config",
                str(config),
            ]
        )
        manifest_name = "avelren-" + result["backup_id"] + ".pair.json"
        manifest_value = paired.pair.load_manifest((download / manifest_name).read_bytes())
        paired.pair.verify_local_pair(manifest_value, download)
        encrypted = [p.read_bytes() for p in remote_dir.rglob("*") if p.is_file()]
        assert len(encrypted) == 5
        assert all(p.read_bytes() not in encrypted for p in download.iterdir())
        assert all(
            p.name not in {q.name for q in remote_dir.rglob("*")} for p in download.iterdir()
        )
        evidence["crypt_ciphertext_differs_verified_plaintext_readback"] = True
        print("Task4 native isolated restore/replay", flush=True)
        restore_env = paired.command_environment(docker=True)
        restore_env["TMPDIR"] = str(fixture)
        restored = command(
            [
                "bash",
                str(root / "ops/paired-restore-rehearsal.sh"),
                "--directory",
                str(download),
                "--manifest",
                manifest_name,
                "--app-image",
                helper,
            ],
            env=restore_env,
            seconds=600,
        )
        safe = next(json.loads(line) for line in restored.splitlines() if line.startswith("{"))
        assert safe["pending_after"] == 0
        evidence["native_restore_receipt"] = safe
        events = [
            json.loads(line) for line in (fixture / "lifecycle.jsonl").read_text().splitlines()
        ]
        generations = list(dict.fromkeys(event["generation"] for event in events))
        assert len(generations) == 2
        killed, successful = [
            [event["event"] for event in events if event["generation"] == g] for g in generations
        ]
        assert killed == ["on_ack", "owned_jobs_absent_before_off", "off_ack"]
        assert successful == [
            "on_ack",
            "sql_snapshot_complete",
            "spool_snapshot_complete",
            "owned_jobs_absent_before_off",
            "off_ack",
        ]
        evidence["native_lifecycle_events"] = events
        evidence["status"] = "PASS"
    except BaseException as failure:
        first_failure = type(failure).__name__
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(signum, signal.SIG_IGN)
        if "manifest" in locals():
            try:
                logs = subprocess.run(
                    ["docker", "logs", manifest["container_name"]],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                Path("/evidence/paired-backup-daemon.log").write_text(logs.stdout + logs.stderr)
                Path("/evidence/paired-backup-status.json").write_text(json.dumps(status()))
            except BaseException:
                pass  # Diagnostics never replace the original failure/cancellation.
        raise
    finally:
        receipt_cleanup = cleanup_fixture(
            fixture,
            args.prefix,
            ownership(),
            coordinator_pid=coordinator_pid,
            first_failure=first_failure,
        )
        if receipt_cleanup["errors"] and first_failure is None:
            raise AssertionError("fixture_cleanup_failed")
    evidence["fixture_resources_cleanup"] = "PASS"
    Path("/evidence/paired-backup-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--local-base", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.cleanup_only:
        sys.exit(cleanup_only(arguments))
    run(arguments)
