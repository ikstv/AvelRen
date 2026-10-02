package ua.avelren.app.notify

import java.time.Instant
import java.util.UUID

val surgeKinds = setOf("surge_forecast", "surge_started")

data class SurgePayload(
    val kind: String,
    val alertId: Long,
    val attemptId: String,
    val ordinal: Long,
    val createdAt: String,
    val expiresAt: String,
    val checkpointId: Int,
    val title: String,
    val body: String,
) {
    companion object {
        fun fromData(data: Map<String, String>): SurgePayload? = runCatching {
            SurgePayload(
                data.getValue("type"), data.getValue("surge_alert_id").toLong(),
                data.getValue("attempt_id"), data.getValue("attempt_ordinal").toLong(),
                data.getValue("attempt_created_at"), data.getValue("expires_at"),
                data.getValue("checkpoint_id").toInt(), data.getValue("title"), data.getValue("body"),
            ).takeIf { it.kind in surgeKinds && it.alertId > 0 && it.ordinal > 0 && it.checkpointId > 0 }
        }.getOrNull()
    }
}

object SurgeDeliveryPolicy {
    fun notificationBody(body: String): String = body + "\nФункція в розробці"
    fun shouldPresent(payload: SurgePayload, now: Instant): Boolean = runCatching {
        payload.kind in surgeKinds && payload.alertId > 0 && payload.ordinal > 0 &&
            payload.checkpointId > 0 && UUID.fromString(payload.attemptId).toString() == payload.attemptId &&
            Instant.parse(payload.createdAt) <= now && Instant.parse(payload.expiresAt) > now &&
            Instant.parse(payload.createdAt) < Instant.parse(payload.expiresAt)
    }.getOrDefault(false)
}
