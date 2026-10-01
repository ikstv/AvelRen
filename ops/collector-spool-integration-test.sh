#!/usr/bin/env bash
# Disposable Docker project: volume permissions + restart persistence, no upstream.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT="avelren-spool-test-${RANDOM}-${RANDOM}"
readonly ROOT PROJECT

compose() {
    docker compose -p "$PROJECT" -f "$ROOT/ops/compose.collector-spool-test.yml" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    compose down --volumes --remove-orphans || status=1
    exit "$status"
}
trap cleanup EXIT

compose build collector-test
compose up -d collector-test
compose exec -T collector-test python - <<'PY'
import os
from datetime import UTC, datetime
from pathlib import Path

from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult

path = Path('/var/lib/avelren/collector-spool/cycles.sqlite3')
assert os.geteuid() == 10001
store = SpoolStore(path)
seq = store.begin(datetime(2026, 10, 1, 12, 0, tzinfo=UTC))
store.finish(seq, FetchResult(None, 429, 1, None, 'HTTP 429'), 1)
assert path.parent.stat().st_mode & 0o777 == 0o700
assert path.stat().st_mode & 0o777 == 0o600
store.close()
PY

compose restart collector-test
compose exec -T collector-test python - <<'PY'
from pathlib import Path

from avelren.collector_spool import SpoolStore

store = SpoolStore(Path('/var/lib/avelren/collector-spool/cycles.sqlite3'))
cycle = store.next_pending()
assert cycle is not None and cycle.seq == 1 and cycle.error == 'HTTP 429'
store.close()
PY

printf '%s\n' 'collector spool volume restart contract ok'
