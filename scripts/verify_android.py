"""Походження Android-блока, ресурси й канонічні примітки релізу."""

import hashlib
import json
import struct
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "docs/ANDROID-PROVENANCE.json").read_text(encoding="utf-8"))
for entry in manifest["files"]:
    expected = entry.get("revision", {}).get("sha256", entry["sha256"])
    if "revision" in entry and not (root / entry["revision"]["notes"]).is_file():
        raise SystemExit(f"Missing revision notes: {entry['destination']}")
    if hashlib.sha256((root / entry["destination"]).read_bytes()).hexdigest() != expected:
        raise SystemExit(f"SHA-256 mismatch: {entry['destination']}")

# A manifest hash alone cannot detect a mistakenly re-hashed corrupt binary.
# Validate the sfnt checksum independently; text newline conversion breaks it.
for font in (root / "apps/android/app/src/main/res/font").glob("*.ttf"):
    raw = font.read_bytes()
    padded = raw + b"\0" * (-len(raw) % 4)
    checksum = sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF
    if checksum != 0xB1B0AFBA:
        raise SystemExit(f"Invalid TTF checksum: {font.name}")

assets = (root / "docs/ASSETS.md").read_text(encoding="utf-8")
for file in (root / "apps/android/app/src/main").rglob("*"):
    if (
        file.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".ttf", ".otf", ".mp3", ".mp4"}
        and file.relative_to(root).as_posix() not in assets
    ):
        raise SystemExit(f"Missing asset provenance: {file.name}")

# The connected test APK must exercise the real main activity and production API
# while remaining a separate package that cannot register a duplicate FCM device.
gradle = (root / "apps/android/app/build.gradle.kts").read_text(encoding="utf-8")
connected_manifest_path = root / "apps/android/app/src/connectedTest/AndroidManifest.xml"
application = (
    root / "apps/android/app/src/main/java/ua/avelren/app/AvelRenApp.kt"
).read_text(encoding="utf-8")
for required in (
    'providers.gradleProperty("avelrenConnectedTest")',
    'applicationIdSuffix = ".connectedtest"',
    'versionNameSuffix = "-connected-test"',
    'buildConfigField("boolean", "ENABLE_PUSH", "false")',
    'manifest.srcFile("src/connectedTest/AndroidManifest.xml")',
):
    if required not in gradle:
        raise SystemExit(f"Connected test APK contract missing from Gradle: {required}")
if not connected_manifest_path.is_file():
    raise SystemExit("Connected test APK manifest is missing")
if "BuildConfig.ENABLE_PUSH" not in application:
    raise SystemExit("Connected test APK must disable push registration in AvelRenApp")

about_screen = (
    root / "apps/android/app/src/main/java/ua/avelren/app/ui/AdministrationScreen.kt"
).read_text(encoding="utf-8")
for version in ("0.1.0", "0.1.1", "0.1.2", "1.0.3"):
    asset = f"release-notes/v{version}.uk.txt"
    notes_path = root / "apps/android/app/src/main/assets" / asset
    notes = notes_path.read_text(encoding="utf-8").rstrip("\r\n")
    if not notes or len(notes) > 500:
        raise SystemExit(
            f"Release {version} notes must contain 1–500 Unicode characters; got {len(notes)}"
        )
    if asset not in about_screen:
        raise SystemExit(f"About screen does not read the canonical {version} release notes")
print(f"Android: verified {len(manifest['files'])} source records and asset provenance")
