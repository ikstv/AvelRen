package ua.avelren.app.data

import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Freshness belongs to the observation, never to the last successful HTTP call. */
object DataRecency {
    data class Info(val title: String, val detail: String, val attention: Boolean)

    fun describe(observedAt: String?, now: Instant, internet: InternetState, responseSucceeded: Boolean?): Info {
        val observed = observedAt?.let { runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull() }
            ?.takeIf { !it.isAfter(now.plusSeconds(60)) }
        val freshness = LiveRefresh.freshness(observed?.toString(), now)
        val detail = observed?.let {
            "Вимірювання: ${it.atZone(ZoneId.of("Europe/Kyiv")).format(DateTimeFormatter.ofPattern("dd.MM HH:mm:ss"))} · ${freshness.label}"
        } ?: "Час вимірювання невідомий. Актуальність черги не підтверджена."
        return when {
            internet == InternetState.OFFLINE -> Info(if (observed != null) "Немає інтернету · показано попередні дані" else "Немає інтернету", detail, true)
            responseSucceeded == false -> Info(if (observed != null) "Не вдалося оновити · показано попередні дані" else "Не вдалося оновити дані", detail, true)
            observed == null -> Info("Актуальність даних невідома", detail, true)
            freshness.stale -> Info("Дані застаріли", detail, true)
            responseSucceeded == null -> Info("Перевіряємо оновлення", detail, true)
            else -> Info("Дані актуальні", detail, false)
        }
    }
}
