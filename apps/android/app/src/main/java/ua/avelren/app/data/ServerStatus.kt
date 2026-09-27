package ua.avelren.app.data

import java.time.Duration
import java.time.Instant
import kotlinx.serialization.Serializable

enum class InternetState { UNKNOWN, OFFLINE, ONLINE, WEAK }

@Serializable
data class MaintenanceWindow(
    val starts_at: String,
    val ends_at: String,
    val restarts_at: String? = null,
) {
    fun bounds(now: Instant): Pair<Instant, Instant>? = runCatching {
        val start = Instant.parse(starts_at)
        val end = Instant.parse(ends_at)
        val restart = restarts_at?.let(Instant::parse)
        val duration = Duration.between(start, end).seconds
        if (duration !in 1..900 || end <= now || start > now.plusSeconds(86400) ||
            (restart != null && (restart <= start || restart >= end))) null
        else start to end
    }.getOrNull()

    fun active(now: Instant): Boolean = bounds(now)?.let { now >= it.first } == true

    fun restartDue(now: Instant): Boolean = active(now) && restarts_at?.let {
        runCatching { now >= Instant.parse(it) }.getOrDefault(false)
    } == true

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
    RESTARTING("ПЕРЕЗАПУСК СЕРВЕРА"),
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
            // The API confirmed this short window before it became unavailable.
            // With working device connectivity that makes a reboot truthful, not
            // a guess from stale data or a generic server outage.
            maintenance?.active(now) == true &&
                (responseSucceeded == false || maintenance.restartDue(now)) -> RESTARTING
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
