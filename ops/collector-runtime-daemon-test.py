"""Ізольований Docker acceptance: штатний daemon, synthetic HTTP, справжній control."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path("/work")
DB_IMAGE = "timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9"
SPOOL = "/var/lib/avelren/collector-spool"
DEVICE = "11111111-1111-4111-8111-111111111111"
SYNTHETIC = """import os
if os.environ.get('AVELREN_RUNTIME_TEST_SYNTHETIC') == '1':
    import json,time,httpx
    from pathlib import Path
    original=httpx.AsyncClient
    def response(request):
        assert str(request.url)=='https://back.echerha.gov.ua/api/v5/workload/1'
        assert request.headers['X-Device-Id']=='11111111-1111-4111-8111-111111111111'
        assert 'Authorization' not in request.headers and 'Cookie' not in request.headers
        trace=Path('/var/lib/avelren/collector-spool/synthetic-requests.jsonl')
        number=len(trace.read_text().splitlines())+1 if trace.exists() else 1
        with trace.open('a') as stream:
            stream.write(json.dumps({'at':time.time()})+'\\n'); stream.flush(); os.fsync(stream.fileno())
        return httpx.Response(200,json={'filters':{'countries':[{'id':1,'name':'Poland'}]},'data':[{'id':7,'title':'Synthetic truck','country_id':1,'for_vehicle_type':1,'wait_time':3600,'vehicle_in_active_queues_counts':60 if number<=2 else 0}]})
    httpx.AsyncClient=lambda *args,**kwargs: original(*args,transport=httpx.MockTransport(response),**kwargs)
"""
CHECK = """import json,hashlib,os
from pathlib import Path
from dataclasses import asdict
from avelren.collector_spool import SpoolStore
p=Path('/var/lib/avelren/collector-spool/cycles.sqlite3')
s=SpoolStore(p)
assert p.stat().st_mode&0o777==0o600 and p.parent.stat().st_mode&0o777==0o700
assert os.geteuid()==10001
assert s.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert all(hashlib.sha256(payload).hexdigest()==digest for payload,digest in s.conn.execute('SELECT payload,payload_sha256 FROM cycles WHERE payload IS NOT NULL'))
trace=p.parent/'synthetic-requests.jsonl'
calls=[json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
assert all(b['at']-a['at']>=59.5 for a,b in zip(calls,calls[1:]))
print(json.dumps(dict(status=asdict(s.status()),calls=calls),default=str)); s.close()
"""
VERIFY = """import json,hashlib,psycopg,os
from pathlib import Path
from avelren.collector_spool import SpoolStore
s=SpoolStore(Path('/var/lib/avelren/collector-spool/cycles.sqlite3'))
expected=[at for (at,) in s.conn.execute("SELECT at FROM cycles WHERE state='acked' ORDER BY seq")]
with psycopg.connect(os.environ['DATABASE_URL']) as conn:
    actual=[row[0].isoformat() for row in conn.execute('SELECT time FROM collector_runs ORDER BY time')]
    order=[row[0].isoformat() for row in conn.execute('SELECT at FROM spool_replay_order ORDER BY seq')]
    assert actual==expected==order,(len(actual),len(expected),len(order))
    assert conn.execute('SELECT count(*) FROM observations').fetchone()[0]==len(expected)
    measurements=conn.execute('SELECT wait_time_seconds,vehicles_in_queue FROM observations ORDER BY time').fetchall()
    assert measurements[:2]==[(3600,60),(3600,60)]
    assert all(row==(3600,0) for row in measurements[2:])
    phases=conn.execute('SELECT derived_processed_at,derived_error FROM collector_runs ORDER BY time').fetchall()
    assert all(row[0] is not None for row in phases)
    assert all('delayed_replay_over_120s' in row[1] for row in phases[:2])
    assert conn.execute('SELECT count(*) FROM alerts').fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM eta_alerts').fetchone()[0]==0
print(json.dumps({'db_cycles':len(expected),'fifo':True,'duplicate_alerts':False})); s.close()
"""


def command(args, *, seconds=180, text=True):
    result = subprocess.run(
        args, capture_output=True, text=text, timeout=seconds, check=False
    )
    if result.returncode:
        # Synthetic-only output; retain a short diagnostic, no production credentials exist here.
        tail = (str(result.stderr) + str(result.stdout))[-1800:]
        raise AssertionError(f"test command failed: {args[0:3]} {tail}")
    return result.stdout


def wait(check, seconds=100):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        value = check()
        if value:
            return value
        time.sleep(1)
    raise AssertionError("synthetic acceptance timed out")


def wait_for_pending_cycle(check, previous_count, seconds=90):
    """Require a fresh completed capture while all prior cycles are pending."""
    def ready():
        snapshot = check()
        count = len(snapshot["calls"])
        return count > previous_count and snapshot["status"]["pending_count"] == count

    wait(ready, seconds)


def wait_for_replayed_cycle(check, previous_count, seconds=90):
    """Require a new HTTP attempt and its completed FIFO replay after rollback."""
    def ready():
        snapshot = check()
        count = len(snapshot["calls"])
        return (
            count > previous_count
            and snapshot["status"]["pending_count"] == 0
            and snapshot["status"]["acked_count"] == count
        )

    wait(ready, seconds)


def cleanup_resources(containers: list[str], volume: str | None, network: str | None):
    if not all(
        re.fullmatch("avelren-runtime-test-[a-z0-9-]+", name)
        for name in (volume, network)
        if name is not None
    ) or not all(re.fullmatch("[0-9a-f]{64}", item) for item in containers):
        raise ValueError("unsafe_cleanup_resource")
    errors = []
    commands = [
        ["docker", "rm", "-f", "-v", identifier] for identifier in reversed(containers)
    ]
    if volume is not None:
        commands.append(["docker", "volume", "rm", volume])
    if network is not None:
        commands.append(["docker", "network", "rm", network])
    for args in commands:
        try:
            command(args)
        except (AssertionError, OSError, subprocess.TimeoutExpired):
            errors.append(args[1])
    if errors:
        raise AssertionError("synthetic cleanup failed: " + ",".join(errors))


def main(source):
    assert len(source) == 40 and all(x in "0123456789abcdef" for x in source)
    prefix = "avelren-runtime-test-" + uuid.uuid4().hex[:10]
    containers = []
    created_volume = created_network = None
    volume, network = prefix + "-spool", prefix + "-network"
    db, canonical = prefix + "-db", prefix + "-collector"
    evidence = {"source_commit": source, "project": prefix, "handoffs": []}
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        path = Path(directory)
        try:
            print("build isolated images", flush=True)
            base = prefix + "-base"
            command(
                [
                    "docker",
                    "build",
                    "--build-arg",
                    "SOURCE_COMMIT=" + source,
                    "-t",
                    base,
                    str(ROOT / "services/backend"),
                ],
                seconds=600,
            )
            (path / "sitecustomize.py").write_text(SYNTHETIC)
            shutil.copy(
                ROOT / "ops/collector-spool-daemon-test.py", path / "spool-driver.py"
            )
            shutil.copytree(ROOT / "db", path / "db")
            (path / "ops").mkdir()
            shutil.copy(
                ROOT / "ops/postgres-bootstrap.sh", path / "ops/postgres-bootstrap.sh"
            )
            (path / "Dockerfile").write_text(
                f"FROM {base}\nCOPY . /synthetic\nENV PYTHONPATH=/synthetic AVELREN_RUNTIME_TEST_SYNTHETIC=1\n"
            )
            image_tag = prefix + "-fixture"
            command(["docker", "build", "-t", image_tag, str(path)], seconds=180)
            image = json.loads(command(["docker", "image", "inspect", image_tag]))[0][
                "Id"
            ]
            evidence["image_id"] = image
            command(["docker", "network", "create", "--internal", network])
            created_network = network
            command(["docker", "volume", "create", volume])
            created_volume = volume
            # Isolated database has its own anonymous data volume, never a production mount.
            db_id = command(
                [
                    "docker",
                    "create",
                    "--name",
                    db,
                    "--network",
                    network,
                    "--network-alias",
                    "runtime-db",
                    "-e",
                    "POSTGRES_USER=avelren_admin",
                    "-e",
                    "POSTGRES_PASSWORD=ci-only",
                    "-e",
                    "POSTGRES_DB=postgres",
                    DB_IMAGE,
                    "postgres",
                    "-c",
                    "timescaledb.telemetry_level=off",
                ]
            ).strip()
            containers.append(db_id)
            command(["docker", "cp", str(path / "ops"), db + ":/tmp/ops"])
            command(["docker", "cp", str(path / "db"), db + ":/tmp/db"])
            command(["docker", "start", db])

            def db_ready():
                return (
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            db,
                            "pg_isready",
                            "-h",
                            "127.0.0.1",
                            "-U",
                            "avelren_admin",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    ).returncode
                    == 0
                )

            wait(db_ready)
            roles = [
                "ADMIN",
                "MIGRATOR",
                "BACKUP",
                "COLLECTOR",
                "NOTIFIER",
                "WATCHDOG",
                "API",
            ]
            bootstrap = [
                "docker",
                "exec",
                "-e",
                "AVELREN_TEST_DB=1",
                "-e",
                "AVELREN_DB_NAME=avelren_runtime_test",
                "-e",
                "AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres",
            ]
            for role in roles:
                bootstrap += ["-e", "AVELREN_" + role + "_PASSWORD=ci-only"]
            command([*bootstrap, db, "bash", "/tmp/ops/postgres-bootstrap.sh", "fresh"])

            def dsn(role):
                return (
                    "postgresql://"
                    + role
                    + ":ci-only@runtime-db:5432/avelren_runtime_test"
                )

            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    network,
                    "-e",
                    "DATABASE_URL=" + dsn("avelren_migrator"),
                    image,
                    "python",
                    "-m",
                    "avelren.migrate",
                    "/synthetic/db/migrations",
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
                    image,
                    "python",
                    "/synthetic/spool-driver.py",
                    "seed",
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
                    image,
                    "python",
                    "-c",
                    'import os; os.chown("'
                    + SPOOL
                    + '",10001,10001); os.chmod("'
                    + SPOOL
                    + '",0o700)',
                ]
            )
            env_file = path / "collector.env"
            env_file.write_text(
                "DATABASE_URL="
                + dsn("avelren_collector")
                + "\nECHERHA_DEVICE_ID="
                + DEVICE
                + "\nECHERHA_DEVICE_NAME=Synthetic runtime collector\nLITERAL_SENTINEL=$PASSWORD 'quoted'\n"
            )
            env_file.chmod(0o600)
            security = [
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "128",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,size=64m",
                "--restart",
                "unless-stopped",
                "--user",
                "10001:10001",
            ]
            standalone = command(
                [
                    "docker",
                    "create",
                    "--name",
                    canonical,
                    "--network",
                    network,
                    "-v",
                    volume + ":" + SPOOL,
                    "--env-file",
                    str(env_file),
                    *security,
                    image,
                    "python",
                    "-m",
                    "avelren.collector",
                ]
            ).strip()
            containers.append(standalone)
            command(["docker", "stop", db])
            command(["docker", "start", canonical])

            def check():
                return json.loads(
                    command(["docker", "exec", canonical, "python", "-c", CHECK])
                )

            print("capture two pending cycles with database offline", flush=True)
            # Startup pause + two captures at t=60/120, with scheduling margin.
            wait(lambda: check()["status"]["pending_count"] >= 2, 150)
            command(
                [
                    "docker",
                    "exec",
                    canonical,
                    "python",
                    "-m",
                    "avelren.collector_control",
                    "capture-only",
                    "on",
                ]
            )
            backup_code = (
                "from pathlib import Path; from avelren.collector_spool import SpoolStore; "
                's=SpoolStore(Path("'
                + SPOOL
                + '/cycles.sqlite3")); s.backup_to(Path("'
                + SPOOL
                + '/acceptance-backup.sqlite3")); s.close()'
            )
            command(["docker", "exec", canonical, "python", "-c", backup_code])
            command(
                [
                    "docker",
                    "cp",
                    canonical + ":" + SPOOL + "/acceptance-backup.sqlite3",
                    str(path / "outside-volume.sqlite3"),
                ]
            )
            evidence["backup_sha256"] = hashlib.sha256(
                (path / "outside-volume.sqlite3").read_bytes()
            ).hexdigest()
            import sqlite3

            with sqlite3.connect(path / "outside-volume.sqlite3") as backup:
                assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert (
                    backup.execute(
                        "SELECT count(*) FROM cycles WHERE state='pending'"
                    ).fetchone()[0]
                    >= 2
                )
                assert all(
                    hashlib.sha256(p).hexdigest() == d
                    for p, d in backup.execute(
                        "SELECT payload,payload_sha256 FROM cycles WHERE payload IS NOT NULL"
                    )
                )
            command(["docker", "stop", "--time", "30", canonical])
            stopped_at = time.monotonic()
            command(["docker", "rename", canonical, prefix + "-rollback"])
            state = path / "state"
            state.mkdir(mode=0o700)
            manifest = {
                "source_commit": source,
                "image_id": image,
                "env_file": str(env_file),
                "compose_file": str(ROOT / "ops/compose.collector-runtime.yml"),
                "project": prefix,
                "container_name": canonical,
                "network": network,
                "volume": volume,
                "state_dir": str(state),
            }
            manifest_path = path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            manifest_path.chmod(0o600)
            compose_env = dict(
                os.environ,
                COLLECTOR_IMAGE_ID=image,
                COLLECTOR_ENV_FILE=str(env_file),
                COLLECTOR_CONTAINER_NAME=canonical,
                COLLECTOR_NETWORK=network,
                COLLECTOR_VOLUME=volume,
            )
            create = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    "/dev/null",
                    "-p",
                    prefix,
                    "-f",
                    manifest["compose_file"],
                    "create",
                    "--no-build",
                    "--pull",
                    "never",
                    "collector",
                ],
                env=compose_env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert create.returncode == 0, create.stderr
            managed_id = json.loads(command(["docker", "inspect", canonical]))[0]["Id"]
            containers.append(managed_id)

            def control(action, *args):
                return json.loads(
                    command(
                        [
                            "bash",
                            str(ROOT / "ops/collector-runtime-control.sh"),
                            "--manifest",
                            str(manifest_path),
                            "--test-mode",
                            action,
                            *args,
                        ],
                        seconds=100,
                    )
                )

            print(
                "handoff standalone → Compose using real 60s operator delay", flush=True
            )
            # Compose selects all project/service labels, including renamed stopped rollback.
            duplicate = command(
                [
                    "docker",
                    "create",
                    "--name",
                    prefix + "-duplicate",
                    "--network",
                    "none",
                    "--label",
                    "com.docker.compose.project=" + prefix,
                    "--label",
                    "com.docker.compose.service=collector",
                    image,
                    "python",
                    "-c",
                    "pass",
                ]
            ).strip()
            containers.append(duplicate)
            denied = subprocess.run(
                [
                    "bash",
                    str(ROOT / "ops/collector-runtime-control.sh"),
                    "--manifest",
                    str(manifest_path),
                    "--test-mode",
                    "start",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert denied.returncode != 0
            assert "LITERAL_SENTINEL" not in denied.stdout + denied.stderr
            assert not any(
                item["State"]["Running"]
                for item in json.loads(
                    command(["docker", "inspect", managed_id, duplicate])
                )
            )
            command(["docker", "rm", "-v", duplicate])
            containers.remove(duplicate)
            evidence["duplicate_stopped_service_denied_before_start"] = True
            control("start")
            evidence["handoffs"].append(
                {"kind": "compose", "pause_seconds": time.monotonic() - stopped_at}
            )
            assert evidence["handoffs"][-1]["pause_seconds"] >= 60
            wait(lambda: check()["status"]["mode_ack"] is True, 15)
            assert check()["status"]["pending_count"] >= 2
            handoff_count = len(check()["calls"])
            wait_for_pending_cycle(check, handoff_count)
            item = json.loads(command(["docker", "inspect", canonical]))[0]
            assert "LITERAL_SENTINEL=$PASSWORD 'quoted'" in item["Config"]["Env"]
            assert "ECHERHA_DEVICE_ID=" + DEVICE in item["Config"]["Env"]
            assert item["Image"] == image and item["Mounts"][0]["Name"] == volume
            print("age both threshold-crossing pending cycles beyond 120s", flush=True)
            wait(lambda: time.time() - check()["calls"][1]["at"] > 121, 130)
            command(["docker", "start", db])
            wait(db_ready)
            print("schema ack and FIFO replay", flush=True)
            control("capture-only", "off")
            wait(lambda: check()["status"]["pending_count"] == 0, 45)
            print("managed restart with real lock and 60s delay", flush=True)
            control("restart")
            wait(lambda: check()["status"]["pending_count"] == 0, 25)
            control("capture-only", "on")
            # Preserve a pending cycle for rollback, not only an empty spool.
            count = len(check()["calls"])
            wait(
                lambda: (
                    len(check()["calls"]) > count
                    and check()["status"]["pending_count"] > 0
                ),
                75,
            )
            control("stop")
            stopped_at = time.monotonic()
            command(["docker", "rename", canonical, prefix + "-managed-stopped"])
            command(["docker", "rename", prefix + "-rollback", canonical])
            print(
                "rollback to compatible standalone with pending preserved", flush=True
            )
            time.sleep(max(0, 60 - (time.monotonic() - stopped_at)))
            command(["docker", "start", canonical])
            evidence["handoffs"].append(
                {"kind": "rollback", "pause_seconds": time.monotonic() - stopped_at}
            )
            wait(lambda: check()["status"]["mode_ack"] is True, 15)
            assert check()["status"]["pending_count"] > 0
            rollback_count = len(check()["calls"])
            command(
                [
                    "docker",
                    "exec",
                    canonical,
                    "python",
                    "-m",
                    "avelren.collector_control",
                    "capture-only",
                    "off",
                ]
            )
            wait_for_replayed_cycle(check, rollback_count)
            command(
                [
                    "docker",
                    "exec",
                    canonical,
                    "python",
                    "-m",
                    "avelren.collector_control",
                    "capture-only",
                    "on",
                ]
            )
            evidence["verification"] = json.loads(
                command(
                    [
                        "docker",
                        "exec",
                        "-e",
                        "DATABASE_URL=" + dsn("avelren_admin"),
                        canonical,
                        "python",
                        "-c",
                        VERIFY,
                    ]
                )
            )
            final = check()
            evidence["cycles"] = len(final["calls"])
            evidence["pending"] = final["status"]["pending_count"]
            assert evidence["cycles"] >= 5 and evidence["pending"] == 0, (
                evidence["cycles"], evidence["pending"],
            )
            items = json.loads(command(["docker", "inspect", standalone, managed_id]))
            assert sum(x["State"]["Running"] for x in items) == 1
            evidence["status"] = "PASS"
        finally:
            cleanup_resources(containers, created_volume, created_network)
        evidence["cleanup"] = "PASS"
        Path("/evidence/collector-runtime-evidence.json").write_text(
            json.dumps(evidence, indent=2)
        )
        print(json.dumps(evidence), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    main(parser.parse_args().source_commit)
