#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
# Обидва runner створюють власні випадкові проєкти та прибирають їх через trap.
# Жодних production volumes, collector, Firebase або запитів до єЧерги.
bash "$ROOT/scripts/test_database.sh" surge
bash "$ROOT/ops/restore-integration-test.sh"
