package ua.avelren.app.ui

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val releaseDateFormat = DateTimeFormatter.ofPattern("d MMMM uuuu 'року'", Locale.forLanguageTag("uk"))
private val releaseZone = ZoneId.of("Europe/Kyiv")

internal fun releaseHistoryHeading(version: String, publishedAt: Instant?): String {
    val date = publishedAt?.atZone(releaseZone)?.format(releaseDateFormat) ?: "у підготовці"
    return "Версія $version · $date"
}
