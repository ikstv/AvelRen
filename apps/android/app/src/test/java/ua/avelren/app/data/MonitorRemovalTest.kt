package ua.avelren.app.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MonitorRemovalTest {
    @Test
    fun `successful deletion reconciles notifications after server confirmation`() = runBlocking {
        val events = mutableListOf<String>()
        removeMonitorAndReconcile(
            remove = { events += "server deleted" },
            reconcile = { events += "reconciled" },
        )
        assertEquals(listOf("server deleted", "reconciled"), events)
    }

    @Test
    fun `failed deletion preserves shown notifications`() = runBlocking {
        var reconciled = false
        val result = runCatching {
            removeMonitorAndReconcile(
                remove = { error("offline") },
                reconcile = { reconciled = true },
            )
        }
        assertTrue(result.isFailure)
        assertEquals(false, reconciled)
    }
}
