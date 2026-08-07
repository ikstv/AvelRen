package ua.avelren.app.data

import kotlinx.coroutines.delay
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

/**
 * Чиста логіка живого оновлення даних черги (AND-4), винесена з Compose заради
 * JVM-тестування. Compose лише запускає/скасовує [poll] через `repeatOnLifecycle`
 * і малює [Freshness]; уся поведінка — тут.
 */
object LiveRefresh {

    /** Період автооновлення у foreground. */
    const val INTERVAL_MS: Long = 60_000

    /** Дані вважаються застарілими після 3 циклів збору (3×60 c) без свіжого
     *  observation — узгоджено з частотою збирача, без backend-зміни. */
    const val STALE_AFTER_SECONDS: Long = 180

    data class Freshness(val label: String, val stale: Boolean)

    /**
     * Оцінка свіжості за server observation time (НЕ за часом HTTP-запиту).
     * `null` або нерозбірний час → невідомо + stale. Викликач передає `time`
     * саме обраного КПП; якщо той зник зі snapshot — теж передає `null`, і ми
     * НЕ підміняємо його чужим часом.
     */
    fun freshness(
        observationIso: String?,
        now: Instant,
        staleAfterSeconds: Long = STALE_AFTER_SECONDS,
    ): Freshness {
        val obs = observationIso
            ?.let { runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull() }
            ?: return Freshness("оновлення невідоме", stale = true)

        val ageSec = Duration.between(obs, now).seconds.coerceAtLeast(0)
        val label = if (ageSec < 60) "щойно" else "${ageSec / 60} хв тому"
        return Freshness(label, stale = ageSec > staleAfterSeconds)
    }

    /**
     * Keep-last-on-error: при успіху — нові дані, при помилці — попередній
     * валідний snapshot (ніколи не затираємо його порожнім/`null`). Workload і
     * forecast застосовують це незалежно, тож збій одного не блокує інший.
     */
    fun <T> keepOnError(previous: T, attempt: Result<T>): T =
        attempt.getOrDefault(previous)

    /**
     * Foreground-цикл: refresh ОДРАЗУ, потім кожні [intervalMs]. Скасування
     * корутини зупиняє подальші оновлення. `repeatOnLifecycle(RESUMED)` у
     * Compose запускає це при вході/поверненні (миттєвий refresh) і скасовує при
     * згортанні.
     */
    suspend fun poll(intervalMs: Long = INTERVAL_MS, refresh: suspend () -> Unit) {
        while (true) {
            refresh()
            delay(intervalMs)
        }
    }
}
