package ua.avelren.app.notify

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class SurgeAckPersistenceTest {
    private class Disk : SurgePersistence {
        var value: String? = null
        var fail = false
        override fun load(): String? = value
        override fun save(value: String): Boolean {
            if (fail) return false
            this.value = value
            return true
        }
    }
    private val now = Instant.parse("2026-10-02T10:00:00Z")
    private fun payload(ordinal: Long = 1) = SurgePayload("surge_forecast", 42,
        "00000000-0000-4000-8000-" + ordinal.toString().padStart(12, '0'), ordinal,
        now.minusSeconds(10).toString(), now.plusSeconds(60).toString(), 17, "Чоп", "fixture")

    @Test fun `ACK survives recreation and late reminder cannot unset it`() {
        val disk = Disk()
        val first = SurgeLocalStore(disk)
        assertTrue(first.claimAttempt(payload(), now))
        assertTrue(first.acknowledge(42))
        val rebooted = SurgeLocalStore(disk)
        assertTrue(rebooted.isAcknowledged(42))
        assertFalse(rebooted.claimAttempt(payload(2), now))
        assertEquals(setOf(42L), rebooted.pendingAcks())
        assertTrue(rebooted.confirmAck(42))
        assertTrue(SurgeLocalStore(disk).isAcknowledged(42))
        assertTrue(SurgeLocalStore(disk).pendingAcks().isEmpty())
    }
    @Test fun `duplicate and out of order attempts survive restart`() {
        val disk = Disk()
        assertTrue(SurgeLocalStore(disk).claimAttempt(payload(2), now))
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(2), now))
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(1), now))
        assertTrue(SurgeLocalStore(disk).claimAttempt(payload(3), now))
    }
    @Test fun `cancel arriving before normal is a durable tombstone`() {
        val disk = Disk()
        assertTrue(SurgeLocalStore(disk).cancel(42))
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(), now))
        assertTrue(SurgeLocalStore(disk).pendingAcks().isEmpty())
    }
    @Test fun `failed persistence fails closed and can retry later`() {
        val disk = Disk().apply { fail = true }
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(), now))
        disk.fail = false
        assertTrue(SurgeLocalStore(disk).claimAttempt(payload(), now))
    }
    @Test fun `known active fact blocks later forecast for same checkpoint`() {
        val disk = Disk()
        val store = SurgeLocalStore(disk)
        assertTrue(store.claimAttempt(payload().copy(kind = "surge_started", alertId = 43), now))
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(), now))
        assertTrue(SurgeLocalStore(disk).claimAttempt(payload().copy(checkpointId = 6), now))
    }
    @Test fun `fact atomically suppresses already shown forecast for same checkpoint`() {
        val disk = Disk()
        val store = SurgeLocalStore(disk)
        assertTrue(store.claimAttempt(payload(), now))
        assertTrue(store.claimAttempt(payload().copy(kind = "surge_started", alertId = 43), now))
        assertTrue(SurgeLocalStore(disk).isBlocked(42))
        assertFalse(SurgeLocalStore(disk).claimAttempt(payload(2), now))
    }

}
