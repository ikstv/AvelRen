package ua.avelren.app.notify

/**
 * Чиста логіка звірки показаних сповіщень із canonical server-станом (A-02).
 *
 * Винесена окремо від Android-фреймворку саме щоб бути тестованою на JVM без
 * інструментації: тут немає жодного залежного від пристрою виклику.
 *
 * Ключове рішення: сповіщення НЕ ідентифікуються через display-id
 * `notificationId()`. Той id — `kindCode * 10^7 + alertId % 10^7` — необоротний
 * (alertId у bigserial легко перевищує 10^7), тож відновити з нього alertId
 * неможливо. Тому нові сповіщення несуть повний `kind + Long alertId` у
 * extras, а reconciliation працює з цим повним ключем. Для сповіщень, показаних
 * ще старою версією (без extras), лишається вузький legacy-шлях за display-id.
 */
data class AlertKey(val kind: String, val alertId: Long)

/**
 * Показане сповіщення в термінах reconciliation.
 *
 * @param notificationId Android display-id (для фактичного cancel).
 * @param key Повний ключ з extras або null, якщо сповіщення старе/чуже.
 */
data class ActiveNotification(val notificationId: Int, val key: AlertKey?)

object AlertReconciliation {

    // Мусить збігатися з Notifications.notificationId(): kindCode * SPAN.
    const val SPAN = 10_000_000
    private const val KIND_THRESHOLD = 1
    private const val KIND_ETA = 2

    /**
     * Повертає display-id сповіщень, які треба погасити: тих, чий alert більше
     * не входить у server pending-набір.
     *
     * Health та невідомі сповіщення (без extras і не з нашого namespace)
     * НІКОЛИ не чіпаються — reconciliation стосується лише alert-backed
     * сповіщень (threshold/eta).
     *
     * Виклик має відбуватися ЛИШЕ після успішного отримання server-стану:
     * порожній `serverPending` тут означає «сервер сказав: активних немає»,
     * а не «не вдалося спитати». За fail-safe відповідає викликач.
     */
    fun staleNotificationIds(
        active: List<ActiveNotification>,
        serverPending: Set<AlertKey>,
    ): List<Int> {
        // Для legacy-сповіщень (без extras) порівнюємо за усіченим id, бо
        // повного alertId в них немає. Колізія можлива лише в межах 10^7 і лише
        // для старих сповіщень — свідомо прийнятний компроміс.
        val serverLegacy = serverPending.mapTo(HashSet()) { AlertKey(it.kind, it.alertId % SPAN) }

        return active.mapNotNull { n ->
            val key = n.key
            if (key != null) {
                if (key !in serverPending) n.notificationId else null
            } else {
                val legacy = legacyKeyFromNotificationId(n.notificationId)
                when {
                    legacy == null -> null // health/невідоме — не чіпаємо
                    legacy !in serverLegacy -> n.notificationId
                    else -> null
                }
            }
        }
    }

    /**
     * Fail-safe обгортка (A-02): `serverPending == null` означає, що canonical
     * стан отримати НЕ вдалося (offline / 5xx / 401 до завершення recovery) —
     * тоді не гасимо нічого. Порожній набір (не null) — це підтверджене «сервер
     * каже: активних немає», і воно таки гасить. Викликач передає null саме на
     * будь-якому винятку fetch-у.
     */
    fun staleNotificationIdsOrNothing(
        active: List<ActiveNotification>,
        serverPending: Set<AlertKey>?,
    ): List<Int> =
        if (serverPending == null) emptyList()
        else staleNotificationIds(active, serverPending)

    /**
     * Відновлює усічений ключ зі старого display-id (сповіщення без extras).
     * Повертає null для health (kindCode=3) і будь-чого невідомого.
     */
    fun legacyKeyFromNotificationId(notificationId: Int): AlertKey? {
        val kind = when (notificationId / SPAN) {
            KIND_THRESHOLD -> "threshold"
            KIND_ETA -> "eta"
            else -> return null
        }
        return AlertKey(kind, (notificationId % SPAN).toLong())
    }
}
