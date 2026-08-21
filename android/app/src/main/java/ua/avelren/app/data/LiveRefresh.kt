package ua.avelren.app.data

import kotlinx.coroutines.delay
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

/**
 * Pure logic for live-refreshing the queue data (AND-4), extracted from Compose
 * for JVM testing. Compose only starts/cancels [poll] via `repeatOnLifecycle`
 * and draws [Freshness]; all the behavior is here.
 */
object LiveRefresh {

    /** Auto-refresh interval in the foreground. */
    const val INTERVAL_MS: Long = 60_000

    /** Data is considered stale after 3 collection cycles (3×60 s) without a fresh
     *  observation — aligned with the collector's frequency, without a backend change. */
    const val STALE_AFTER_SECONDS: Long = 180

    data class Freshness(val label: String, val stale: Boolean)

    /**
     * Freshness estimate by server observation time (NOT by the HTTP request time).
     * `null` or an unparseable time → unknown + stale. The caller passes the `time`
     * of the selected checkpoint specifically; if it disappeared from the snapshot
     * it passes `null` too, and we do NOT substitute someone else's time for it.
     */
    fun freshness(
        observationIso: String?,
        now: Instant,
        staleAfterSeconds: Long = STALE_AFTER_SECONDS,
    ): Freshness {
        val obs = observationIso
            ?.let { runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull() }
            ?: return Freshness("невідомо", stale = true)

        val ageSec = Duration.between(obs, now).seconds.coerceAtLeast(0)
        val label = if (ageSec < 60) "щойно" else "${ageSec / 60} хв тому"
        return Freshness(label, stale = ageSec > staleAfterSeconds)
    }

    /**
     * Keep-last-on-error: on success — new data, on error — the previous valid
     * snapshot (we never overwrite it with empty/`null`). Workload and forecast
     * apply this independently, so a failure of one does not block the other.
     */
    fun <T> keepOnError(previous: T, attempt: Result<T>): T =
        attempt.getOrDefault(previous)

    /**
     * Keep-last for the forecast, bound specifically to the selected checkpoint.
     * Otherwise a slow or failed forecast request for a new checkpoint would leave
     * the previous one's forecast on screen — while the card already shows a
     * different point (people plan their time by this). We accept the cached value
     * only if it belongs to the same checkpoint as the selected one.
     */
    fun scopedForecast(
        previous: Api.Forecast?,
        attempt: Result<Api.Forecast?>,
        selectedCheckpoint: Int,
    ): Api.Forecast? {
        val previousForSelected = previous?.takeIf { it.checkpoint_id == selectedCheckpoint }
        return attempt.getOrDefault(previousForSelected)
    }

    /**
     * Foreground loop: refresh IMMEDIATELY, then every [intervalMs]. Cancelling
     * the coroutine stops further refreshes. `repeatOnLifecycle(RESUMED)` in
     * Compose starts this on entry/return (an immediate refresh) and cancels it on
     * backgrounding.
     */
    suspend fun poll(intervalMs: Long = INTERVAL_MS, refresh: suspend () -> Unit) {
        while (true) {
            refresh()
            delay(intervalMs)
        }
    }
}
