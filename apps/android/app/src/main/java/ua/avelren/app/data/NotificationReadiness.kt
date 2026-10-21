package ua.avelren.app.data

/** Read-only system evidence; no successful snapshot can guarantee audible delivery. */
object NotificationReadiness {
    enum class Status { Observed, Attention, Unknown }
    data class Indicator(val title: String, val detail: String, val status: Status)
    data class Snapshot(
        val runtimePermissionGranted: Boolean? = null,
        val appNotificationsEnabled: Boolean? = null,
        val queueChannelExists: Boolean? = null,
        val queueChannelImportance: Int? = null,
        val queueChannelSoundUri: String? = null,
        val alarmVolume: Int? = null,
        val alarmMaxVolume: Int? = null,
        val ringerMode: Int? = null,
        val interruptionFilter: Int? = null,
    )
    data class Result(val title: String, val detail: String, val indicators: List<Indicator>)

    fun evaluate(snapshot: Snapshot): Result = with(snapshot) {
        val blocked = runtimePermissionGranted == false || appNotificationsEnabled == false ||
            (queueChannelExists == true && queueChannelImportance == 0)
        val quiet = queueChannelExists == true &&
            (queueChannelSoundUri == null || queueChannelImportance in 1..2) || alarmVolume == 0
        val incomplete = runtimePermissionGranted == null || appNotificationsEnabled == null ||
            queueChannelExists != true || queueChannelImportance !in 0..5 || alarmVolume == null ||
            alarmMaxVolume == null || ringerMode !in 0..2 || interruptionFilter !in 1..4
        Result(
            title = when {
                blocked -> "Сповіщення заблоковано"
                quiet -> "Звук потребує уваги"
                incomplete -> "Потрібно перевірити налаштування"
                interruptionFilter in 2..4 -> "Режим «Не турбувати» активний"
                else -> "Сповіщення дозволені"
            },
            detail = "Звук залежить від гучності, режиму «Не турбувати» та обмежень батареї.",
            indicators = listOf(
                Indicator("Дозвіл Android", when (runtimePermissionGranted) {
                    true -> "Надано"
                    false -> "Не надано · відкрийте налаштування"
                    null -> "Не вдалося прочитати"
                }, status(runtimePermissionGranted)),
                Indicator("Сповіщення додатка", when (appNotificationsEnabled) {
                    true -> "Дозволено Android"
                    false -> "Вимкнено в Android"
                    null -> "Не вдалося прочитати"
                }, status(appNotificationsEnabled)),
                Indicator("Канал черги", when {
                    queueChannelExists == false -> "Ще не створено · стан звуку невідомий"
                    queueChannelExists == null || queueChannelImportance !in 0..5 -> "Не вдалося прочитати"
                    queueChannelImportance == 0 -> "Вимкнено в Android"
                    else -> "Важливість: ${importanceLabel(queueChannelImportance ?: -1)} · звук: ${if (queueChannelSoundUri == null) "вимкнено" else "задано"}"
                }, when {
                    queueChannelExists != true || queueChannelImportance !in 0..5 -> Status.Unknown
                    (queueChannelImportance ?: -1) < 3 || queueChannelSoundUri == null -> Status.Attention
                    else -> Status.Observed
                }),
                Indicator("Гучність будильника", if (alarmVolume != null && alarmMaxVolume != null) {
                    "$alarmVolume із $alarmMaxVolume · канал черги використовує звук будильника"
                } else "Не вдалося прочитати", when (alarmVolume) {
                    null -> Status.Unknown
                    0 -> Status.Attention
                    else -> if (alarmMaxVolume == null) Status.Unknown else Status.Observed
                }),
                Indicator("Режим дзвінка", when (ringerMode) {
                    0 -> "Без звуку · це не визначає звук каналу будильника"
                    1 -> "Вібрація · це не визначає звук каналу будильника"
                    2 -> "Звичайний · не гарантує звук сповіщення"
                    else -> "Не вдалося визначити"
                }, if (ringerMode in 0..2) Status.Observed else Status.Unknown),
                Indicator("Не турбувати", when (interruptionFilter) {
                    1 -> "Вимкнено · звук усе одно не гарантовано"
                    2 -> "Лише пріоритетні · звук залежить від правил Android"
                    3 -> "Без переривань · звук може бути заглушено"
                    4 -> "Лише будильники · звук залежить від каналу та правил Android"
                    else -> "Не вдалося визначити режим"
                }, when (interruptionFilter) {
                    1 -> Status.Observed
                    2, 3, 4 -> Status.Attention
                    else -> Status.Unknown
                }),
            ),
        )
    }

    private fun status(value: Boolean?) = when (value) {
        true -> Status.Observed
        false -> Status.Attention
        null -> Status.Unknown
    }

    private fun importanceLabel(value: Int) = when (value) {
        0 -> "вимкнено"
        1 -> "мінімальна"
        2 -> "низька (без звуку)"
        3 -> "звичайна"
        4 -> "висока"
        5 -> "максимальна"
        else -> "невідома"
    }
}
