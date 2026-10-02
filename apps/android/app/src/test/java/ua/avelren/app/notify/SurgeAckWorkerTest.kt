package ua.avelren.app.notify

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class SurgeAckWorkerTest {
    private class Disk : SurgePersistence {
        var value: String? = null
        override fun load(): String? = value
        override fun save(value: String): Boolean { this.value = value; return true }
    }
    @Test fun `offline ACK remains pending until a successful retry`() = runTest {
        val disk = Disk()
        val store = SurgeLocalStore(disk)
        assertTrue(store.acknowledge(42))
        assertFalse(syncSurgeAck(store, 42) { throw java.io.IOException("offline") })
        assertTrue(SurgeLocalStore(disk).isAcknowledged(42))
        assertEquals(setOf(42L), SurgeLocalStore(disk).pendingAcks())
        assertTrue(syncSurgeAck(SurgeLocalStore(disk), 42) { })
        assertTrue(SurgeLocalStore(disk).pendingAcks().isEmpty())
        assertTrue(SurgeLocalStore(disk).isAcknowledged(42))
    }
    @Test fun `confirmed ACK does not perform another network request`() = runTest {
        val store = SurgeLocalStore(Disk())
        assertTrue(syncSurgeAck(store, 42) { fail("nothing pending") })
    }
}
