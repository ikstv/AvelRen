"""Походження Android-блока й обов'язкові записи для бінарних ресурсів."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "docs/ANDROID-PROVENANCE.json").read_text(encoding="utf-8"))
for entry in manifest["files"]:
    expected = entry.get("revision", {}).get("sha256", entry["sha256"])
    if "revision" in entry and not (root / entry["revision"]["notes"]).is_file():
        raise SystemExit(f"Missing revision notes: {entry['destination']}")
    if hashlib.sha256((root / entry["destination"]).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"SHA-256 mismatch: {entry['destination']}")

assets = (root / "docs/ASSETS.md").read_text(encoding="utf-8")
for file in (root / "apps/android/app/src/main").rglob("*"):
    if (
        file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ttf", ".otf", ".mp3", ".mp4"}
        and file.relative_to(root).as_posix() not in assets
    ):
        raise SystemExit(f"Missing asset provenance: {file.name}")
print(f"Android: verified {len(manifest['files'])} source records and asset provenance")
