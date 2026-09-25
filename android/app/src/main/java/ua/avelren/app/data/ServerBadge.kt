package ua.avelren.app.data

import java.time.Instant

/**
 * A planned-maintenance window is cached after the server confirms it.  That is
 * what lets the app distinguish a planned reboot from a phone that merely lost
 * its internet connection while the API is briefly unavailable.
 */
enum class ServerBadge { OFFLINE, RESTARTING, MAINTENANCE, STALE, ONLINE }

fun activeMaintenanceEnd(endsAt: String?, now: Instant): Instant? =
    runCatching { endsAt?.let(Instant::parse) }
        .getOrNull()
        ?.takeIf { it.isAfter(now) }

fun serverBadge(
    hasError: Boolean,
    stale: Boolean,
    maintenanceEndsAt: Instant?,
    now: Instant,
): ServerBadge {
    val planned = maintenanceEndsAt?.isAfter(now) == true
    return when {
        hasError && planned -> ServerBadge.RESTARTING
        planned -> ServerBadge.MAINTENANCE
        hasError -> ServerBadge.OFFLINE
        stale -> ServerBadge.STALE
        else -> ServerBadge.ONLINE
    }
}
