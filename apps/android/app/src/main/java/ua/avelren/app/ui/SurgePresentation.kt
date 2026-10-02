package ua.avelren.app.ui

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import ua.avelren.app.data.SurgeCheckpoint
import ua.avelren.app.data.SurgeStatus

data class SurgeCards(val forecast: String, val fact: String, val window: String? = null)

object SurgePresentation {
    private fun location(cp: SurgeCheckpoint): String = when (cp.checkpoint_id) {
        17 -> "на Чопі"
        6 -> "на Краківці"
        1, 29 -> "на Ягодині"
        else -> "на КПП «${cp.title}»"
    }
    fun cards(cp: SurgeCheckpoint, status: SurgeStatus?, now: Instant): SurgeCards {
        val expired = status?.expires_at?.let { runCatching { Instant.parse(it) <= now }.getOrDefault(true) } == true
        val unavailable = when (status?.reason) {
            "stale", "missing_history", "insufficient_history" -> "Немає свіжих даних для прогнозу"
            "unsupported" -> "Прогноз для цього КПП поки недоступний"
            "prediction_expired" -> "Прогноз застарів. Очікуємо оновлення"
            else -> "Прогноз зараз недоступний"
        }
        val forecast = when {
            !cp.forecast_supported -> "Прогноз для цього КПП поки недоступний"
            expired -> "Попередній сигнал завершився. Очікуємо оновлення"
            status?.status == "risk" -> "Можливий початок масової реєстрації ${location(cp)}"
            status?.status == "started" -> "Зростання вже почалось — дивіться фактичне повідомлення"
            status?.status == "no_signal" -> "Зараз немає сигналу можливого напливу. Він усе одно може початися"
            else -> unavailable
        }
        val fact = when {
            status == null || status.status !in setOf("risk", "started", "no_signal") -> "Статус фактичного зростання зараз недоступний"
            !cp.data_fresh -> "Немає свіжих даних для перевірки зростання"
            !expired && status?.status == "started" -> "Почалось зростання черги ${location(cp)}"
            else -> "Різкого зростання зараз не зафіксовано"
        }
        return SurgeCards(forecast, fact,
            if (!expired && status?.status == "risk") window(status.window_start, status.window_end) else null)
    }
    fun window(start: String?, end: String?): String? = runCatching {
        if (start == null || end == null) return null
        val format = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm").withZone(ZoneId.of("Europe/Kyiv"))
        "${format.format(Instant.parse(start))} — ${format.format(Instant.parse(end))} (Київ)"
    }.getOrNull()
    fun voiceHint(enabled: Boolean, permission: Boolean): String = when {
        !enabled -> "Голос вимкнено"
        !permission -> "Для голосу та повідомлень потрібен дозвіл у налаштуваннях телефону"
        else -> "Голос увімкнено. Повтор кожні 5 хвилин до «Зрозуміло», поки повідомлення актуальне"
    }
}
