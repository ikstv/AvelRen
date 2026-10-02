package ua.avelren.app.notify

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class SurgeDeliveryPolicyTest {
    private val now = Instant.parse("2026-10-02T10:00:00Z")
    private fun payload(kind: String = "surge_forecast", expiry: String = "2026-10-02T10:01:00Z") =
        SurgePayload(kind, 42, "00000000-0000-4000-8000-000000000001", 1,
            "2026-10-02T09:59:00Z", expiry, 17, "Чоп", "fixture")

    @Test fun `expiry invalid and unknown types do not present`() {
        assertTrue(SurgeDeliveryPolicy.shouldPresent(payload(), now))
        assertFalse(SurgeDeliveryPolicy.shouldPresent(payload(expiry = now.toString()), now))
        assertFalse(SurgeDeliveryPolicy.shouldPresent(payload(expiry = "broken"), now))
        assertFalse(SurgeDeliveryPolicy.shouldPresent(payload(kind = "threshold"), now))
        assertFalse(SurgeDeliveryPolicy.shouldPresent(payload().copy(attemptId = "bad"), now))
    }
    @Test fun `parser reads distinct UUID and ordinal contract`() {
        val data = mapOf("type" to "surge_started", "surge_alert_id" to "42",
            "attempt_id" to "00000000-0000-4000-8000-000000000001", "attempt_ordinal" to "2",
            "attempt_created_at" to "2026-10-02T09:59:00Z", "expires_at" to "2026-10-02T10:01:00Z",
            "checkpoint_id" to "17", "title" to "Чоп", "body" to "fixture")
        assertEquals(2L, SurgePayload.fromData(data)?.ordinal)
        assertNull(SurgePayload.fromData(data - "surge_alert_id"))
        assertNull(SurgePayload.fromData(data + ("attempt_ordinal" to "0")))
    }
    @Test fun `new kind IDs cannot collide with legacy IDs`() {
        val ids = listOf("threshold", "eta", "health", "surge_forecast", "surge_started")
            .map { Notifications.notificationId(it, 42) }
        assertEquals(5, ids.toSet().size)
    }

    @Test fun `visible notice includes development label without modifying speech`() {
        val spoken = "Можливий початок масової реєстрації на Чопі"
        assertEquals(spoken + "\nФункція в розробці", SurgeDeliveryPolicy.notificationBody(spoken))
    }
}
