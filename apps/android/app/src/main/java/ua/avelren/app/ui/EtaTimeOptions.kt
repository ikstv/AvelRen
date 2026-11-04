package ua.avelren.app.ui

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

internal fun etaTargetIsFuture(date: LocalDate, hour: Int, now: Instant, zone: ZoneId): Boolean {
    if (hour !in 0..23) return false
    val local = date.atTime(hour, 0)
    val offset = zone.rules.getValidOffsets(local).firstOrNull() ?: return false
    return local.toInstant(offset).isAfter(now)
}

internal fun etaFutureHours(date: LocalDate, now: Instant, zone: ZoneId): List<Int> =
    (0..23).filter { etaTargetIsFuture(date, it, now, zone) }
