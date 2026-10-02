package ua.avelren.app.notify

import java.time.Instant

object SurgeVoicePolicy {
    fun canStart(payload: SurgePayload, now: Instant, pushPriority: Int, isForeground: Boolean,
        voiceEnabled: Boolean, channelAllowed: Boolean): Boolean =
        SurgeDeliveryPolicy.shouldPresent(payload, now) && voiceEnabled && channelAllowed &&
            (isForeground || pushPriority == 1)
}

/** Main-thread queue. No disk replay: only fresh delivered attempts can speak. */
class SurgeVoiceQueue(private val capacity: Int = 10) {
    private val entries = ArrayDeque<SurgePayload>()
    fun offer(payload: SurgePayload, now: Instant): Boolean {
        if (!SurgeDeliveryPolicy.shouldPresent(payload, now)) return false
        if (entries.any { it.attemptId == payload.attemptId }) return false
        if (payload.kind == "surge_started")
            entries.removeAll { it.kind == "surge_forecast" && it.checkpointId == payload.checkpointId }
        if (entries.size >= capacity) return false
        entries.addLast(payload)
        return true
    }
    fun cancel(alertId: Long) { entries.removeAll { it.alertId == alertId } }
    fun next(now: Instant, blocked: (Long) -> Boolean): SurgePayload? {
        while (entries.isNotEmpty()) {
            val next = entries.removeFirst()
            if (SurgeDeliveryPolicy.shouldPresent(next, now) && !blocked(next.alertId)) return next
        }
        return null
    }
    fun clear() = entries.clear()
}
