"""Перевірка фактичного merged manifest і BuildConfig окремого FCM QA APK."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
build = root / "apps/android/app/build"
manifest = build / "intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml"
config = build / "generated/source/buildConfig/debug/ua/avelren/app/BuildConfig.java"
a = "{http://schemas.android.com/apk/res/android}"
m = ET.parse(manifest).getroot()


def require(value, message):
    if not value:
        raise SystemExit(message)


require(m.get("package") == "ua.avelren.app.pushqa", "Wrong QA package")
app = m.find("application")
require(app is not None, "Missing application")
require(app.get(a + "name") == "android.app.Application", "Production Application leaked")
require(app.get(a + "allowBackup") == "false", "QA data must not be backed up")
require(app.get(a + "debuggable") == "true", "QA must be debug only")
activities = {node.get(a + "name"): node for node in app.findall("activity")}
require("ua.avelren.app.MainActivity" not in activities, "Production Activity leaked")
qa = activities.get("ua.avelren.app.PushQaActivity")
require(qa is not None and qa.get(a + "exported") == "true", "Missing QA Activity")
launchers = [node.get(a + "name") for node in app if any(
    category.get(a + "name") == "android.intent.category.LAUNCHER"
    for category in node.findall("intent-filter/category"))]
require(launchers == ["ua.avelren.app.PushQaActivity"], "Unexpected launcher")
aliases = {node.get(a + "name"): node for node in app.findall("activity-alias")}
alias = aliases.get("ua.avelren.app.MainActivity")
require(alias is not None and alias.get(a + "targetActivity") == "ua.avelren.app.PushQaActivity"
        and alias.get(a + "exported") == "false", "Unsafe notification destination")
services = {node.get(a + "name"): node for node in app.findall("service")}
for name in ("AvelRenMessagingService", "SurgeVoiceService"):
    service = services.get("ua.avelren.app.notify." + name)
    require(service is not None and service.get(a + "exported") == "false", "Missing safe " + name)
require(services["ua.avelren.app.notify.SurgeVoiceService"].get(a + "foregroundServiceType") == "shortService",
        "Missing voice foreground service type")
receivers = {node.get(a + "name"): node for node in app.findall("receiver")}
ack = receivers.get("ua.avelren.app.notify.AckReceiver")
require(ack is not None and ack.get(a + "exported") == "false", "Missing local ACK")
probe = receivers.get("ua.avelren.app.SystemVoiceQaReceiver")
require(probe is not None and probe.get(a + "exported") == "true", "Missing isolated local probe")
providers = {node.get(a + "name"): node for node in app.findall("provider")}
voice_provider = providers.get("ua.avelren.app.notify.SurgeVoiceProvider")
require(voice_provider is not None and voice_provider.get(a + "authorities") == "ua.avelren.app.pushqa.surgevoice"
        and voice_provider.get(a + "exported") == "false" and voice_provider.get(a + "grantUriPermissions") == "true",
        "Unsafe voice provider")
require(not any(node.get(a + "name") == "android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK"
                for node in m.findall("uses-permission")), "Obsolete media playback permission")
require(any(node.get(a + "name") == "com.google.firebase.provider.FirebaseInitProvider"
            for node in app.findall("provider")), "Missing Firebase initialization")
require(any(node.get(a + "name") == "android.permission.INTERNET"
            for node in m.findall("uses-permission")), "Missing FCM network access")
text = config.read_text(encoding="utf-8")
for field, value in (("APPLICATION_ID", '"ua.avelren.app.pushqa"'),
                     ("API_BASE_URL", '"https://127.0.0.1:9/api"'), ("ENABLE_PUSH", "true")):
    require(re.search(r"\b" + field + r"\s*=\s*" + re.escape(value) + r"\s*;", text),
            "Unsafe BuildConfig: " + field)
print("Push QA: merged manifest and BuildConfig isolation PASS")
