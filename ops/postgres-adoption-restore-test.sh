#!/usr/bin/env bash
# Join the existing synthetic restore rehearsal with disposable adoption acceptance.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export AVELREN_ADOPTION_RESTORE_ACCEPTANCE=1
exec bash "$ROOT/ops/restore-integration-test.sh"
