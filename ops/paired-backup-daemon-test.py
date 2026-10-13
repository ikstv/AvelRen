"""Real daemon/coordinator/Docker jobs; only upstream HTTP is synthetic."""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

APP = "avelren-app@sha256:9d32a0d54ff9711b54a082f39074e21ba456775b078caf01a293b95109674735"
RCLONE = "rclone/rclone@sha256:2687085f718d3c628f7fdfb77c52a1d344332aed543110bb88088f2c70d43eb5"
DEVICE = "11111111-1111-4111-8111-111111111111"
SPOOL = "/var/lib/avelren/collector-spool"
PLUGIN_HASH = "db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"


def command(argv, *, env=None, seconds=180):
    result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=seconds)
    if result.returncode:
        # Synthetic fixture only; keep raw diagnostics in private evidence.
        Path("/evidence/paired-backup-failure.log").write_text(result.stdout + result.stderr)
        raise AssertionError("fixture_command_failed:" + argv[0])
    return result.stdout


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


def run(args):
    os.umask(0o077)
    assert re.fullmatch(r"[0-9a-f]{40}", args.source_commit)
    assert re.fullmatch(r"avelren-runtime-test-pair-[0-9]+-[0-9]+", args.prefix)
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
    created_volume = created_network = sql_started = False
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
        images.append(base_tag)
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
        command(["docker", "build", "--network", "none", "-t", helper_tag, str(build)], seconds=600)
        images.append(helper_tag)
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
                    "print(json.dumps(dict(uid=os.geteuid(),origin=m.__file__,"
                    "sha256=hashlib.sha256(open(m.__file__,'rb').read()).hexdigest())))",
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
        evidence.update(helper_image_id=helper, installed_helper=proof)
        transport = old.SYNTHETIC.replace(
            "{'at':time.time()}",
            "{'at':time.time(),'monotonic':time.monotonic(),"
            "'device':request.headers['X-Device-Id']}",
        )
        (build / "sitecustomize.py").write_text(transport)
        (build / "sitecustomize.py").chmod(0o644)
        (build / "Dockerfile.collector").write_text(
            f"FROM {helper_tag}\nCOPY sitecustomize.py /synthetic/sitecustomize.py\n"
            "ENV PYTHONPATH=/synthetic AVELREN_RUNTIME_TEST_SYNTHETIC=1\n"
        )
        collector_tag = args.prefix + "-collector-image"
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
        images.append(collector_tag)
        image = json.loads(command(["docker", "image", "inspect", collector_tag]))[0]["Id"]
        evidence["collector_image_id"] = image
        rclone_container = command(["docker", "create", "--network", "none", RCLONE]).strip()
        containers.append(rclone_container)
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
        command(["docker", "network", "create", "--internal", network])
        created_network = True
        command(["docker", "volume", "create", volume])
        created_volume = True
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
        command(
            [*collector_compose, "up", "-d", "--no-build", "--pull", "never", "collector"],
            env=collector_env,
        )
        containers.append(manifest["container_name"])
        api = args.prefix + "-api"
        command(
            [
                "docker",
                "run",
                "-d",
                "--name",
                api,
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
        containers.append(api)

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
                    for kind in ("check", "sql", "spool"):
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
            command(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
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
            containers.append(name)
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
        wait(lambda: len(status()["calls"]) >= 3 and status()["status"]["pending_count"] == 0, 90)
        after = status()["calls"][-1]["at"]
        smoke()
        assert first < during < after
        calls = status()["calls"]
        intervals = [
            b["monotonic"] - a["monotonic"] for a, b in zip(calls, calls[1:], strict=False)
        ]
        assert all(interval >= 60 for interval in intervals), intervals
        assert all(call["device"] == DEVICE for call in calls)
        evidence.update(
            cycles_before_during_after=len(calls),
            start_intervals_seconds=intervals,
            api_smoke_before_during_after=True,
            writer_receipt=result,
            producer_boundary_events=dict(before=first, during=during, after=after),
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
        assert all(
            b["monotonic"] - a["monotonic"] >= 60
            for a, b in zip(final_calls, final_calls[1:], strict=False)
        )
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
    except BaseException:
        if "manifest" in locals():
            logs = subprocess.run(
                ["docker", "logs", manifest["container_name"]],
                capture_output=True,
                text=True,
                timeout=30,
            )
            Path("/evidence/paired-backup-daemon.log").write_text(logs.stdout + logs.stderr)
            Path("/evidence/paired-backup-status.json").write_text(json.dumps(status()))
            diagnostic = command(
                [
                    "docker",
                    "exec",
                    manifest["container_name"],
                    "python",
                    "-c",
                    "import json,os,sys;print(json.dumps(dict(paths=sys.path,"
                    "synthetic=os.environ.get('AVELREN_RUNTIME_TEST_SYNTHETIC'))))",
                ]
            )
            Path("/evidence/paired-backup-transport.json").write_text(diagnostic)
        raise
    finally:
        if coordinator_pid:
            os.kill(coordinator_pid, signal.SIGKILL)
            os.waitpid(coordinator_pid, 0)
        # Only our exact own generation jobs, exact own fixture containers/projects.
        current = state.read_state(fixture / "state") if (fixture / "state").exists() else None
        if current:
            for kind in ("check", "sql", "spool"):
                name = "avelren-paired-" + current["generation"] + "-" + kind
                ids = command(["docker", "ps", "-aq", "--filter", "name=^/" + name + "$"]).split()
                for identifier in ids:
                    info = json.loads(command(["docker", "inspect", identifier]))[0]
                    assert (
                        info["Config"]["Labels"].get("org.avelren.backup.generation")
                        == current["generation"]
                    )
                    command(["docker", "rm", "-f", identifier])
        for name in reversed(containers):
            command(["docker", "rm", "-fv", name])
        if sql_started:
            command([*compose, "down", "--volumes", "--remove-orphans"], env=environment)
        for kind, name, created in (
            ("volume", volume, created_volume),
            ("network", network, created_network),
        ):
            if created:
                command(["docker", kind, "rm", name])
        for tag in reversed(images):
            command(["docker", "image", "rm", tag])
        remaining = command(["docker", "ps", "-a", "--format", "{{.Names}}"])
        assert all(
            name == args.prefix + "-controller" or not name.startswith(args.prefix)
            for name in remaining.splitlines()
        )
        assert not command(
            [
                "docker",
                "volume",
                "ls",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + sql_project,
            ]
        ).strip()
    evidence["fixture_resources_cleanup"] = "PASS"
    Path("/evidence/paired-backup-evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--local-base", action="store_true")
    run(parser.parse_args())
