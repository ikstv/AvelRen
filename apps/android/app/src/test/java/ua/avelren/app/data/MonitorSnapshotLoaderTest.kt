package ua.avelren.app.data

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class MonitorSnapshotLoaderTest {
    @Test fun `both monitor requests start before either finishes`() = runTest {
        val started = CompletableDeferred<Unit>()
        val result = async {
            loadMonitorSnapshot(
                { started.await(); listOf("threshold") },
                { started.complete(Unit); listOf("eta") },
            )
        }.await()
        assertEquals(listOf("threshold") to listOf("eta"), result)
    }

    @Test fun `failure never publishes a partial monitor snapshot`() = runTest {
        var published: Pair<List<String>, List<String>>? = null
        try {
            published = loadMonitorSnapshot({ listOf("threshold") }, { error("offline") })
            fail("partial snapshot must not be published")
        } catch (e: IllegalStateException) {
            assertEquals("offline", e.message)
        }
        assertNull(published)
    }

    @Test fun `cancellation remains cancellation`() = runTest {
        try {
            loadMonitorSnapshot<String, String>({ throw CancellationException("leaving screen") }, { emptyList() })
            fail("cancellation must propagate")
        } catch (e: CancellationException) {
            assertEquals("leaving screen", e.message)
        }
    }
}
