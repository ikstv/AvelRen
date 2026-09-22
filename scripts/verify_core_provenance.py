"""Перевірка незмінності перенесених Git blobs за маніфестом."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "docs/CORE-PROVENANCE.json").read_text(encoding="utf-8"))
for entry in manifest["files"]:
    file = root / entry["destination"]
    if hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
        raise SystemExit(f"SHA-256 mismatch: {entry['destination']}")
print(f"Verified {len(manifest['files'])} unchanged files")
