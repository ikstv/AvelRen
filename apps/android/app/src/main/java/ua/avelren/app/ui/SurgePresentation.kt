package ua.avelren.app.ui

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import ua.avelren.app.data.SurgeCheckpoint
import ua.avelren.app.data.SurgeStatus

data class SurgeCards(val forecast: String, val fact: String, val window: String? = null)

object SurgePresentation {
    private fun location(cp: SurgeCheckpoint): String =
        ua.avelren.app.data.CheckpointSpeech.location(cp.checkpoint_id, cp.title)
    fun availabilityHint(cp: SurgeCheckpoint, status: SurgeStatus?): String? = when {
        status == null -> "Не вдалося оновити дані КПП"
        !cp.data_fresh -> "Дані КПП застаріли. Сповіщення можуть затримуватися"
        status.status == "unavailable" && status.reason != "unsupported" -> "Перевірка зростання тимчасово недоступна"
        else -> null
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
            status?.status == "no_signal" -> "Зараз немає сигналу початку масової реєстрації. Вона все одно може початися"
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
    fun voiceHint(enabled: Boolean, permission: Boolean, problem: String? = null): String = when {
        !enabled -> "Голос вимкнено"
        !permission -> "Для голосу та повідомлень потрібен дозвіл у налаштуваннях телефону"
        problem == "uk_unavailable" -> "Не встановлено український голос. Додайте його в налаштуваннях телефону"
        problem == "tts_unavailable" -> "Озвучення зараз недоступне. Перевірте налаштування голосу телефону"
        problem == "background_limited" -> "Телефон обмежив фонове озвучення. Текстове повідомлення залишається"
        problem == "audio_busy" -> "Голос не відтворився: звук був зайнятий. Текстове повідомлення залишається"
        else -> "Голос увімкнено. Повтор кожні 5 хвилин до «Зрозуміло», поки повідомлення актуальне"
    }
}
