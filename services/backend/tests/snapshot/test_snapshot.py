"""Виконуємо точний shell-сценарій з синтетичними операційними журналами."""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "ops/telemetry-snapshot.sh"
OUT = Path("/var/lib/avelren-telemetry/host.json")


@pytest.fixture
def snapshot(tmp_path):
    bins = tmp_path / "bin"
    bins.mkdir()

    def executable(name, body):
        file = bins / name
        file.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        file.chmod(0o755)
        return file

    executable("openssl", "exit 1")
    executable("apt", "printf 'Listing...\\npackage-one/new\\npackage-two/new\\n'")
    executable("journalctl", "printf 'synthetic error 1\\nsynthetic error 2\\n'")
    executable(
        "docker",
        """
case "$*" in
  "compose logs"*)
    printf '%s\\n' 'caddy | {"level":"warn","error":"benign"}' \\
      'api | ERROR synthetic' 'caddy | {"level":"error","msg":"synthetic"}' ;;
  "compose --profile migrate config") echo "${SYNTHETIC_PIN:-/synthetic/pin}" ;;
  "version"*) echo 'synthetic' ;;
  "compose version"*) echo 'synthetic' ;;
  "inspect"*) echo 'running|healthy|2026-09-22T00:00:00Z|0|0|false|synthetic:test' ;;
  *) exit 1 ;;
esac
""",
    )
    probe = executable("apt-check", "echo '5;2' >&2")
    net = tmp_path / "net-dev"
    net.write_text(
        "header\nheader\n"
        "    lo: 500000000000 0 0 0 0 0 0 0 500000000000 0 0 0 0 0 0 0\n"
        " docker0: 400000000000 0 0 0 0 0 0 0 400000000000 0 0 0 0 0 0 0\n"
        " veth0: 300000000000 0 0 0 0 0 0 0 300000000000 0 0 0 0 0 0 0\n"
        " br-test: 200000000000 0 0 0 0 0 0 0 200000000000 0 0 0 0 0 0 0\n"
        " eth0: 1073741824 0 0 0 0 0 0 0 2147483648 0 0 0 0 0 0 0\n",
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        PATH=f"{bins}:{os.environ['PATH']}",
        AVELREN_FS_PROBE="/",
        AVELREN_CERT_HOST="127.0.0.1",
        AVELREN_STACK_DIR=str(tmp_path),
        AVELREN_MIGRATE_PIN_PATH="/synthetic/pin",
        AVELREN_APT_CHECK=str(probe),
        AVELREN_NET_DEV=str(net),
    )
    log = Path("/var/log/unattended-upgrades/unattended-upgrades.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(
        "2020-01-01 00:00:00 INFO Packages that will be upgraded: old\n"
        "2020-01-01 00:00:01 INFO All upgrades installed\n"
        f"{now} INFO Packages that will be upgraded: one two\n"
        f"{now} INFO All upgrades installed\n"
        f"{now} INFO Packages that will be upgraded: failed-package\n"
        f"{now} ERROR synthetic failure\n",
        encoding="utf-8",
    )

    def run(**overrides):
        subprocess.run(
            ["bash", str(SCRIPT)],
            env=env | overrides,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        data = json.loads(OUT.read_text(encoding="utf-8"))
        assert data["script_sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
        assert not OUT.with_suffix(".json.tmp").exists()
        return data

    return run, executable, tmp_path


def test_full_snapshot_and_log_counts(snapshot):
    run, _, _ = snapshot
    data = run()
    system = data["system"]
    assert system["updates_pending"] == 5
    assert system["updates_upgradable"] == 2
    assert system["updates_security"] == 2
    assert system["updates_installed_24h"] == 2
    assert system["update_failures_24h"] == 1
    assert system["journal_errors_24h"] == 2
    assert system["compose_errors_24h"] == 2
    assert system["rebooted_24h"] == (system["uptime_seconds"] < 86400)
    assert data["network"] == {"rx_total_gb": 1.0, "tx_total_gb": 2.0}
    assert data["docker"]["migrate_pin_active"] is True
    assert len(data["services"]) == 6
    assert all(s["exit_code"] is None for s in data["services"])
    assert data["certificate"]["error"] == "handshake failed"


@pytest.mark.parametrize("probe,expected", [("missing", None), ("failed", None), ("zero", 0)])
def test_unknown_updates_are_not_zero(snapshot, probe, expected):
    run, executable, tmp_path = snapshot
    path = tmp_path / "missing"
    if probe != "missing":
        path = executable("special-probe", "exit 1" if probe == "failed" else "echo '0;0' >&2")
    system = run(AVELREN_APT_CHECK=str(path))["system"]
    assert system["updates_pending"] == expected
    assert system["updates_security"] == expected


def test_pin_absent_or_unknown(snapshot):
    run, _, tmp_path = snapshot
    assert run(SYNTHETIC_PIN="/different/path")["docker"]["migrate_pin_active"] is False
    assert run(AVELREN_STACK_DIR=str(tmp_path / "missing"))["docker"]["migrate_pin_active"] is None
