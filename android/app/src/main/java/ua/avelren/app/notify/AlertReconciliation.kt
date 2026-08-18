package ua.avelren.app.notify

/**
 * Pure logic for reconciling shown notifications against the canonical server
 * state (A-02).
 *
 * Extracted separately from the Android framework precisely to be testable on the
 * JVM without instrumentation: there is not a single device-dependent call here.
 *
 * Key decision: notifications are NOT identified by the display-id
 * `notificationId()`. That id — `kindCode * 10^7 + alertId % 10^7` — is
 * irreversible (an alertId in a bigserial easily exceeds 10^7), so the alertId
 * cannot be recovered from it. Therefore new notifications carry the full
 * `kind + Long alertId` in extras, and reconciliation works with this full key.
 * For notifications shown by an older version (without extras), a narrow legacy
 * path by display-id remains.
 */
data class AlertKey(val kind: String, val alertId: Long)

/**
 * A shown notification in reconciliation terms.
 *
 * @param notificationId Android display-id (for the actual cancel).
 * @param key The full key from extras, or null if the notification is old/foreign.
 */
data class ActiveNotification(val notificationId: Int, val key: AlertKey?)

object AlertReconciliation {

    // Must match Notifications.notificationId(): kindCode * SPAN.
    const val SPAN = 10_000_000
    private const val KIND_THRESHOLD = 1
    private const val KIND_ETA = 2

    /**
     * Returns the display-ids of notifications that must be dismissed: those whose
     * alert is no longer in the server pending set.
     *
     * Health and unknown notifications (without extras and not from our namespace)
     * are NEVER touched — reconciliation concerns only alert-backed notifications
     * (threshold/eta).
     *
     * The call must happen ONLY after the server state was successfully fetched:
     * an empty `serverPending` here means "the server said: there are no active
     * ones", not "the query failed". Fail-safety is the caller's responsibility.
     */
    fun staleNotificationIds(
        active: List<ActiveNotification>,
        serverPending: Set<AlertKey>,
    ): List<Int> {
        // For legacy notifications (without extras) we compare by the truncated id,
        // because they have no full alertId. A collision is possible only within 10^7
        // and only for old notifications — a deliberately acceptable compromise.
        val serverLegacy = serverPending.mapTo(HashSet()) { AlertKey(it.kind, it.alertId % SPAN) }

        return active.mapNotNull { n ->
            val key = n.key
            if (key != null) {
                if (key !in serverPending) n.notificationId else null
            } else {
                val legacy = legacyKeyFromNotificationId(n.notificationId)
                when {
                    legacy == null -> null // health/unknown — do not touch
                    legacy !in serverLegacy -> n.notificationId
                    else -> null
                }
            }
        }
    }

    /**
     * Fail-safe wrapper (A-02): `serverPending == null` means the canonical state
     * could NOT be fetched (offline / 5xx / 401 before recovery completed) — then
     * we dismiss nothing. An empty set (not null) is a confirmed "the server says:
     * there are no active ones", and it does dismiss. The caller passes null
     * precisely on any fetch exception.
     */
    fun staleNotificationIdsOrNothing(
        active: List<ActiveNotification>,
        serverPending: Set<AlertKey>?,
    ): List<Int> =
        if (serverPending == null) emptyList()
        else staleNotificationIds(active, serverPending)

    /**
     * Recovers the truncated key from an old display-id (a notification without
     * extras). Returns null for health (kindCode=3) and anything unknown.
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
