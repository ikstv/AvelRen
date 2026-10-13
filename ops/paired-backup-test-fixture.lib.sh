# Ізольований root-owned manifest; лише для Linux contract harness.
GUARD_WORK=$(mktemp -d "${AVELREN_GUARD_TEST_ROOT:-/root}/avelren-guard-test.XXXXXX")
chmod 0700 "$GUARD_WORK"
mkdir -m 0700 "$GUARD_WORK/runtime-state"
touch "$GUARD_WORK/private.env" "$GUARD_WORK/compose.yml"
chmod 0600 "$GUARD_WORK/private.env" "$GUARD_WORK/compose.yml"
export AVELREN_RUNTIME_MANIFEST="$GUARD_WORK/manifest.json"
python3 - "$GUARD_WORK" <<'PY'
import json
import os
import sys
from pathlib import Path
p = Path(sys.argv[1])
value = {
    "source_commit": "a" * 40, "image_id": "sha256:" + "b" * 64,
    "env_file": str(p / "private.env"), "compose_file": str(p / "compose.yml"),
    "state_dir": str(p / "runtime-state"), "project": "avelren-collector-runtime",
    "container_name": "avelren-collector-1", "network": "avelren_default",
    "volume": "avelren_collector_spool_v1",
}
(p / "manifest.json").write_text(json.dumps(value))
os.chmod(p / "manifest.json", 0o600)
PY
