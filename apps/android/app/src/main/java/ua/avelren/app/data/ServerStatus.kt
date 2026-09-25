package ua.avelren.app.data

import java.time.Duration
import java.time.Instant
import kotlinx.serialization.Serializable

enum class InternetState { UNKNOWN, OFFLINE, ONLINE, WEAK }

@Serializable
data class MaintenanceWindow(val starts_at: String, val ends_at: String) {
    fun bounds(now: Instant): Pair<Instant, Instant>? = runCatching {
        val start = Instant.parse(starts_at)
        val end = Instant.parse(ends_at)
        val duration = Duration.between(start, end).seconds
        if (duration !in 1..900 || end <= now || start > now.plusSeconds(86400)) null
        else start to end
    }.getOrNull()

    fun active(now: Instant): Boolean = bounds(now)?.let { now >= it.first } == true

    fun remainingMinutes(now: Instant): Long? = bounds(now)
        ?.takeIf { now >= it.first }
        ?.let { (Duration.between(now, it.second).seconds + 59) / 60 }
        ?.coerceAtLeast(1)
}

@Serializable
data class PublicServerStatus(val maintenance: MaintenanceWindow? = null)

enum class ServerStatus(val label: String) {
    CHECKING(""), // Initial uncertainty is not a user-facing server status.
    WEAK_INTERNET("СЛАБКИЙ ІНТЕРНЕТ"),
    NO_INTERNET("НЕМАЄ ІНТЕРНЕТУ"),
    // Diagnostic states remain distinct, but do not invent a user-facing cause.
    UNREACHABLE(""),
    CONNECTION_UNKNOWN(""),
    MAINTENANCE("ТЕХНІЧНІ РОБОТИ"),
    STALE(""),
    NO_DATA(""),
    ONLINE("СЕРВЕР ОНЛАЙН");

    companion object {
        fun resolve(
            internet: InternetState,
            responseSucceeded: Boolean?,
            stale: Boolean?,
            maintenance: MaintenanceWindow?,
            now: Instant,
        ): ServerStatus = when {
            internet == InternetState.OFFLINE -> NO_INTERNET
            maintenance?.active(now) == true -> MAINTENANCE
            responseSucceeded == null -> CHECKING
            !responseSucceeded && internet == InternetState.WEAK -> WEAK_INTERNET
            !responseSucceeded && internet == InternetState.ONLINE -> UNREACHABLE
            !responseSucceeded -> CONNECTION_UNKNOWN
            stale == null -> NO_DATA
            stale -> STALE
            internet == InternetState.WEAK -> WEAK_INTERNET
            else -> ONLINE
        }
    }
}
