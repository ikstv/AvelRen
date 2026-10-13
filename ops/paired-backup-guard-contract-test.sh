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
PY
