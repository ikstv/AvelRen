package ua.avelren.app.ui

internal data class FullTestCheckpointLabel(val name: String, val vehicleCategory: String?)

internal fun fullTestCheckpointLabel(title: String): FullTestCheckpointLabel {
    val categoryStart = title.lastIndexOf(" (для ")
    if (categoryStart <= 0 || !title.endsWith(')')) return FullTestCheckpointLabel(title, null)
    return FullTestCheckpointLabel(
        name = title.substring(0, categoryStart),
        vehicleCategory = title.substring(categoryStart + 2, title.lastIndex),
    )
}
