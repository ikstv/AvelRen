package ua.avelren.app.notify

/** Screen and shade share the same durable local-first acknowledgement rule. */
class SurgeMonitorActions(
    private val local: SurgeLocalStore,
    private val finishAck: (Long, String) -> Unit,
) {
    fun acknowledge(id: Long, kind: String): Boolean {
        if (id <= 0 || kind !in surgeKinds || !local.acknowledge(id)) return false
        finishAck(id, kind)
        return true
    }
}
