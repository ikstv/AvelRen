"""Перевірка перенесених файлів і явно описаних наступних змін."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in (
    "CORE-PROVENANCE.json",
    "DB-PROVENANCE.json",
    "API-PROVENANCE.json",
    "WATCHDOG-PROVENANCE.json",
):
    manifest = json.loads((root / "docs" / name).read_text(encoding="utf-8"))
    revised = 0
    for entry in manifest["files"]:
        file = root / entry["destination"]
        expected = entry["sha256"]
        if "revision" in entry:
            revision = entry["revision"]
            if not (root / revision["notes"]).is_file():
                raise SystemExit(f"Missing revision notes: {entry['destination']}")
            expected = revision["sha256"]
            revised += 1
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise SystemExit(f"SHA-256 mismatch: {entry['destination']}")
    print(f"{name}: verified {len(manifest['files'])} files ({revised} documented revisions)")
