"""Перевірка незмінності перенесених Git blobs за маніфестом."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ("CORE-PROVENANCE.json", "DB-PROVENANCE.json", "API-PROVENANCE.json"):
    manifest = json.loads((root / "docs" / name).read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        file = root / entry["destination"]
        if hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit(f"SHA-256 mismatch: {entry['destination']}")
    print(f"{name}: verified {len(manifest['files'])} unchanged files")
