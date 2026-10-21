"""Контракт згенерованого повнофункціонального Test-варіанта, не APK із фікстурою."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
build = root / "apps/android/app/build"
manifest = build / "intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml"
config = build / "generated/source/buildConfig/debug/ua/avelren/app/BuildConfig.java"
android = "{http://schemas.android.com/apk/res/android}"
tree = ET.parse(manifest).getroot()
app = tree.find("application")


def require(condition, message):
    if not condition:
        raise SystemExit(message)


require(tree.get("package") == "ua.avelren.app.test", "Wrong full Test package")
require(app is not None, "Missing Application")
require(app.get(android + "name") == "ua.avelren.app.AvelRenApp", "Real Application missing")
require(app.get(android + "label") == "AvelRen — 0.1.3 Test", "Wrong Test label")
require(app.get(android + "allowBackup") == "false", "Test data backup enabled")
require(app.get(android + "debuggable") == "true", "Test must be debug only")
launchers = [node.get(android + "name") for node in app if any(
    category.get(android + "name") == "android.intent.category.LAUNCHER"
    for category in node.findall("intent-filter/category"))]
require(launchers == ["ua.avelren.app.MainActivity"], "Real main launcher missing")
require(
    not any("Qa" in node.get(android + "name", "") or "Preview" in node.get(android + "name", "")
            for node in app), "QA or preview component leaked")
services = {node.get(android + "name"): node for node in app.findall("service")}
for name in (
    "ua.avelren.app.notify.AvelRenMessagingService", "ua.avelren.app.notify.SurgeVoiceService"
):
    require(name in services and services[name].get(android + "exported") == "false",
            "Missing private live push/voice service")
providers = {node.get(android + "name"): node for node in app.findall("provider")}
require("com.google.firebase.provider.FirebaseInitProvider" in providers, "Firebase init missing")
voice = providers.get("ua.avelren.app.notify.SurgeVoiceProvider")
require(
    voice is not None and voice.get(android + "authorities") == "ua.avelren.app.test.surgevoice",
    "Test voice authority not isolated")
text = config.read_text(encoding="utf-8")
for field, value in (("APPLICATION_ID", '"ua.avelren.app.test"'),
                     ("API_BASE_URL", '"https://api.bordersignal.pp.ua/api"'),
                     ("VERSION_NAME", '"0.1.3-test"'), ("ENABLE_PUSH", "true"),
                     ("ENABLE_TEST_DRAWER", "true")):
    require(re.search(r"\b" + field + r"\s*=\s*" + re.escape(value) + r"\s*;", text),
            "Wrong full Test BuildConfig: " + field)
print("Full Test: real main/API/FCM/voice, test drawer and isolated package PASS")
