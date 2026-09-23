package ua.avelren.app.notify

internal fun shouldShowReleaseNotice(data: Map<String, String>, installedCode: Int): Boolean {
    if (data["type"] != "health" || data["subtype"] != "app_update") return false
    val available = data["version_code"]?.toIntOrNull() ?: return false
    return available > installedCode && available <= 2_100_000_000
}
