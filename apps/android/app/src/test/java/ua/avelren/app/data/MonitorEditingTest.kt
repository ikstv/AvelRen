package ua.avelren.app.data

import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class MonitorEditingTest {
    private val now = Instant.parse("2026-10-22T10:00:00Z")
    private val old = EditableMonitor(1, 2, threshold = 100)
    private class Client : AppScreenClient {
        val events = mutableListOf<String>()
        var failAt = ""
        var cancelAt = ""
        var subscriptions = listOf(Api.Subscription(1, 2, "КПП", threshold = 100))
        var targets = emptyList<Api.EtaTarget>()
        private fun event(name: String) { events += name; if (cancelAt == name) throw CancellationException(); if (failAt == name) error("offline") }
        override suspend fun monitors(): Pair<List<Api.Subscription>, List<Api.EtaTarget>> { event("load"); return subscriptions to targets }
        override suspend fun subscribe(checkpointId: Int, threshold: Int) { event("create") }
        override suspend fun unsubscribe(subscriptionId: Long) { event("delete") }
        override suspend fun createEtaTarget(checkpointId: Int, targetAtIso: String) { event("create") }
        override suspend fun deleteEtaTarget(targetId: Long) { event("delete") }
        override suspend fun workload(): List<Api.Workload> = error("unused")
        override suspend fun serverStatus(): PublicServerStatus = error("unused")
        override suspend fun history(checkpointId: Int): Api.History = error("unused")
        override suspend fun forecast(checkpointId: Int): Api.Forecast = error("unused")
    }
    @Test fun `create precedes delete with fresh snapshot`() = runBlocking {
        val c = Client()
        assertEquals(MonitorEditStatus.SUCCESS, replaceMonitor(c, old, MonitorValue.Threshold(200), now).status)
        assertEquals(listOf("load", "create", "delete"), c.events)
    }
    @Test fun `failures preserve old and partial is explicit`() = runBlocking {
        for ((stage, status) in listOf("load" to MonitorEditStatus.LOAD_FAILED, "create" to MonitorEditStatus.CREATE_FAILED, "delete" to MonitorEditStatus.PARTIAL)) {
            val c = Client().apply { failAt = stage }
            assertEquals(status, replaceMonitor(c, old, MonitorValue.Threshold(200), now).status)
            assertEquals(if (stage == "load") listOf("load") else if (stage == "create") listOf("load", "create") else listOf("load", "create", "delete"), c.events)
        }
    }
    @Test fun `unchanged invalid and past values never mutate`() = runBlocking {
        val c = Client()
        assertEquals(MonitorEditStatus.NO_CHANGE, replaceMonitor(c, old, MonitorValue.Threshold(100), now).status)
        for (v in listOf(MonitorValue.Threshold(75), MonitorValue.Threshold(450), MonitorValue.Eta("2026-10-22T09:00:00Z"))) {
            assertEquals(MonitorEditStatus.INVALID, replaceMonitor(c, old, v, now).status)
        }
        val eta = EditableMonitor(4, 2, targetAt = "2026-10-23T10:00:00Z")
        assertEquals(MonitorEditStatus.INVALID, replaceMonitor(c, eta, MonitorValue.Eta("2026-10-22T09:00:00Z"), now).status)
        assertTrue(c.events.isEmpty())
    }
    @Test fun `stale identity and duplicate prevent mutation`() = runBlocking {
        for (stale in listOf(old.copy(id = 9), old.copy(checkpointId = 9), old.copy(threshold = 50))) {
            val c = Client()
            assertEquals(MonitorEditStatus.STALE, replaceMonitor(c, stale, MonitorValue.Threshold(200), now).status)
            assertEquals(listOf("load"), c.events)
        }
        val c = Client().apply { subscriptions = subscriptions + Api.Subscription(3, 2, "КПП", threshold = 200) }
        assertEquals(MonitorEditStatus.DUPLICATE, replaceMonitor(c, old, MonitorValue.Threshold(200), now).status)
        assertEquals(listOf("load"), c.events)
    }
    @Test fun `eta compares instants across offsets and replaces safely`() = runBlocking {
        val eta = EditableMonitor(4, 2, targetAt = "2026-10-23T10:00:00Z")
        val c = Client().apply { targets = listOf(Api.EtaTarget(4, 2, "КПП", target_at = "2026-10-23T13:00:00+03:00", tolerance_seconds = 0, is_active = true)) }
        assertEquals(MonitorEditStatus.NO_CHANGE, replaceMonitor(c, eta, MonitorValue.Eta("2026-10-23T13:00:00+03:00"), now).status)
        assertEquals(MonitorEditStatus.SUCCESS, replaceMonitor(c, eta, MonitorValue.Eta("2026-10-23T11:00:00Z"), now).status)
        assertEquals(listOf("load", "create", "delete"), c.events)
    }
    @Test fun `eta duplicate and stale server values do not mutate`() = runBlocking {
        val eta = EditableMonitor(4, 2, targetAt = "2026-10-23T10:00:00Z")
        val c = Client().apply { targets = listOf(
            Api.EtaTarget(4, 2, "КПП", target_at = "2026-10-23T10:00:00Z", tolerance_seconds = 0, is_active = true),
            Api.EtaTarget(5, 2, "КПП", target_at = "2026-10-23T14:00:00+03:00", tolerance_seconds = 0, is_active = true),
        ) }
        assertEquals(MonitorEditStatus.DUPLICATE, replaceMonitor(c, eta, MonitorValue.Eta("2026-10-23T11:00:00Z"), now).status)
        assertEquals(MonitorEditStatus.STALE, replaceMonitor(c, eta.copy(targetAt = "2026-10-23T09:00:00Z"), MonitorValue.Eta("2026-10-23T12:00:00Z"), now).status)
        assertEquals(listOf("load", "load"), c.events)
    }
    @Test fun `cancellation propagates from all stages`() = runBlocking {
        for (stage in listOf("load", "create", "delete")) {
            try { replaceMonitor(Client().apply { cancelAt = stage }, old, MonitorValue.Threshold(200), now); fail("must cancel") }
            catch (_: CancellationException) { }
        }
    }
}

