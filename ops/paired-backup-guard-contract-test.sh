#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source "$ROOT/ops/paired-backup-test-fixture.lib.sh"
trap 'rm -rf "$GUARD_WORK"' EXIT
mkdir -m 0700 "$GUARD_WORK/bin"
export GUARD_MARKER="$GUARD_WORK/mutation"
for name in curl docker systemctl publisher; do
  cat >"$GUARD_WORK/bin/$name" <<'SH'
#!/usr/bin/env bash
printf 'mutation\n' >>"$GUARD_MARKER"
exit 71
SH
  chmod +x "$GUARD_WORK/bin/$name"
done
export PATH="$GUARD_WORK/bin:$PATH"
export AVELREN_MAINTENANCE_PUBLISHER="$GUARD_WORK/bin/publisher"
export AVELREN_MAINTENANCE_DIR="$GUARD_WORK/maintenance"
python3 - "$ROOT" "$GUARD_WORK" <<'PY'
import fcntl
import os
import subprocess
import sys
import signal
import time
from pathlib import Path
root, work = map(Path, sys.argv[1:])
state = work / "runtime-state"
marker = work / "mutation"
scripts = [
    ["bash", str(root / "ops/maintenance-window.sh")],
    ["bash", str(root / "ops/maintenance-reboot.sh")],
    ["bash", str(root / "ops/restore-production.sh"), "--artifact", "missing", "--sidecar", "missing", "--evidence", "missing"],
]
fd = os.open(state / "operator-backup.lock", os.O_RDWR | os.O_CREAT, 0o600)
for mode in ("active", "unresolved", "missing_manifest", "forged_authority"):
    if mode == "active":
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif mode == "unresolved":
        fcntl.flock(fd, fcntl.LOCK_UN)
        p = state / "paired-backup-state.json"
        p.write_text('{"format_version":1,"phase":"on_intent"}')
        p.chmod(0o600)
    else:
        (state / "paired-backup-state.json").unlink(missing_ok=True)
    for command in scripts:
        env = dict(os.environ)
        if mode == "missing_manifest":
            env["AVELREN_RUNTIME_MANIFEST"] = str(work / "absent.json")
        if mode == "forged_authority":
            env["AVELREN_OPERATOR_GUARD_FD"] = "99"
        result = subprocess.run(command, env=env, capture_output=True, timeout=5)
        assert result.returncode != 0, (mode, command, "mutation accepted")
        assert not marker.exists(), (mode, command, "external mutation happened")
        assert not (work / "maintenance").exists(), (mode, command, "publication directory mutated")
os.close(fd)
print("paired backup operator guard: PASS")

# Run the actual restore EXIT trap and stop/verify functions. Only Docker/Compose
# boundaries are replaced with private local service-state files.
body = r'''
set -euo pipefail
source "$1/ops/restore-production.sh"
FIXTURE=$2
services=(caddy api collector notifier watchdog)
avelren_compose() {
    local service=${@: -1}
    case "$1" in
        stop)
            if [ "$service" = caddy ]; then
                touch "$FIXTURE/cleanup-started"
                while [ ! -e "$FIXTURE/release-cleanup" ]; do sleep .01; done
            fi
            printf 'exited\n' >"$FIXTURE/$service"
            ;;
        ps)
            [ "$*" = "ps --all --quiet $service" ] || return 43
            for index in "${!services[@]}"; do
                if [ "${services[$index]}" = "$service" ]; then
                    printf '%064x\n' "$((index+1))"
                fi
            done
            ;;
        *) return 44 ;;
    esac
}
docker() {
    [ "$1" = inspect ] && [ "$2" = --format ] && [ "$3" = '{{.State.Status}}' ] || return 45
    local id=${4: -1}
    cat "$FIXTURE/${services[$((id-1))]}"
}
AVELREN_RESTORE_PHASE=restored
AVELREN_RESTORE_MAINTENANCE_STARTED=true
trap avelren_restore_exit_trap EXIT
trap 'printf "HUP\n" >"$FIXTURE/received-signal"; exit 129' HUP
trap 'printf "INT\n" >"$FIXTURE/received-signal"; exit 130' INT
trap 'printf "TERM\n" >"$FIXTURE/received-signal"; exit 143' TERM
touch "$FIXTURE/ready"
sleep 60
'''
for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT, signal.SIGKILL):
    fixture = work / ("restore-signal-" + str(sig))
    fixture.mkdir(mode=0o700)
    for service in ("caddy", "api", "collector", "notifier", "watchdog"):
        (fixture / service).write_text("running\n")
    command = [sys.executable, str(root / "ops/paired_backup_state.py"),
               "--manifest", os.environ["AVELREN_RUNTIME_MANIFEST"], "operator", "--",
               "bash", "-c", body, "bash", str(root), str(fixture)]
    wrapper = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        until = time.monotonic() + 3
        while not (fixture / "ready").exists() and time.monotonic() < until:
            time.sleep(.01)
        assert (fixture / "ready").exists(), (sig, "restore fixture did not start")
        wrapper.send_signal(sig)
        until = time.monotonic() + 3
        while not (fixture / "cleanup-started").exists() and time.monotonic() < until:
            time.sleep(.01)
        assert (fixture / "cleanup-started").exists(), (sig, "actual restore EXIT cleanup bypassed")
        probe = os.open(state / "operator-backup.lock", os.O_RDWR)
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise AssertionError((sig, "lease released during restore cleanup"))
        finally:
            os.close(probe)
        expected_signal = {signal.SIGTERM: "TERM\n", signal.SIGHUP: "HUP\n",
                           signal.SIGINT: "INT\n", signal.SIGKILL: "TERM\n"}[sig]
        assert (fixture / "received-signal").read_text() == expected_signal
        (fixture / "release-cleanup").touch()
        stdout, stderr = wrapper.communicate(timeout=4)
        assert wrapper.returncode != 0, (sig, "cancelled restore reported success")
        for service in ("caddy", "api", "collector", "notifier", "watchdog"):
            assert (fixture / service).read_text() == "exited\n", (sig, service, "not stopped")
        assert b"failure_state=stopped-verified" in stderr, (sig, stderr)
        probe = os.open(state / "operator-backup.lock", os.O_RDWR)
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(probe)
    finally:
        (fixture / "release-cleanup").touch()
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.communicate(timeout=4)
print("guarded actual restore EXIT cleanup: TERM/HUP/INT/KILL PASS")
PY
