package ua.avelren.app.notify

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class SurgeVoicePolicyTest {
    private val now = Instant.parse("2026-10-02T10:00:00Z")
    private fun payload(id: Long = 42, kind: String = "surge_forecast", cp: Int = 17) = SurgePayload(kind, id,
        "00000000-0000-4000-8000-" + id.toString().padStart(12, '0'), 1,
        now.minusSeconds(1).toString(), now.plusSeconds(60).toString(), cp, "fixture", "fixture")
    @Test fun `background normal priority does not start voice but foreground can`() {
        assertFalse(SurgeVoicePolicy.canStart(payload(), now, 2, false, true, true))
        assertTrue(SurgeVoicePolicy.canStart(payload(), now, 1, false, true, true))
        assertTrue(SurgeVoicePolicy.canStart(payload(), now, 2, true, true, true))
    }
    @Test fun `disabled permission and expiry block voice`() {
        assertFalse(SurgeVoicePolicy.canStart(payload(), now, 1, true, false, true))
        assertFalse(SurgeVoicePolicy.canStart(payload(), now, 1, true, true, false))
        assertFalse(SurgeVoicePolicy.canStart(payload().copy(expiresAt = now.toString()), now, 1, true, true, true))
    }
    @Test fun `queue bounded duplicate cancelled and expired entries do not speak`() {
        val queue = SurgeVoiceQueue(2)
        assertTrue(queue.offer(payload(), now))
        assertFalse(queue.offer(payload(), now))
        assertTrue(queue.offer(payload(43, cp = 6), now))
        assertFalse(queue.offer(payload(44, cp = 29), now))
        queue.cancel(42)
        assertEquals(43L, queue.next(now) { false }?.alertId)
        assertNull(queue.next(now) { false })
        assertFalse(queue.offer(payload().copy(expiresAt = now.toString()), now))
    }
    @Test fun `fact removes queued forecast only for same checkpoint`() {
        val queue = SurgeVoiceQueue()
        queue.offer(payload(), now)
        queue.offer(payload(43, cp = 6), now)
        queue.offer(payload(44, kind = "surge_started"), now)
        assertEquals(43L, queue.next(now) { false }?.alertId)
        assertEquals(44L, queue.next(now) { false }?.alertId)
        assertNull(queue.next(now) { false })
    }
    @Test fun `ACK arriving while TTS initializes is checked before speech`() {
        val queue = SurgeVoiceQueue()
        queue.offer(payload(), now)
        assertNull(queue.next(now) { it == 42L })
    }
}
