package ua.avelren.app.ui

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal fun telemetryTimeLabel(measured: Instant, now: Instant): String {
    val zone = ZoneId.of("Europe/Kyiv")
    val stamp = measured.atZone(zone)
    val today = now.atZone(zone).toLocalDate()
    val date = stamp.toLocalDate()
    val day = when (date) {
        today -> "сьогодні"
        today.minusDays(1) -> "вчора"
        else -> DateTimeFormatter.ofPattern(if (date.year == today.year) "dd.MM" else "dd.MM.yyyy",
            Locale.ROOT).format(date)
    }
    return "$day о ${DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT).format(stamp)}"
}
