package ua.avelren.app

import java.time.Instant
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class PreviewAppClientTest {
    private val now = Instant.parse("2026-10-06T09:00:00Z")
    @Test fun `return from offline preserves edited selection`() = runTest {
        val client = PreviewAppClient(PreviewScenario.FIVE_CHECKPOINTS) { now }
        client.removeSubscription(6)
        client.setScenario(PreviewScenario.OFFLINE)
        client.setScenario(PreviewScenario.FIVE_CHECKPOINTS)
        assertEquals(listOf(17, 1, 29, 5), client.subscriptions().map { it.checkpoint_id })
    }
    @Test fun `empty scenario has no subscriptions`() = runTest {
        assertTrue(PreviewAppClient(PreviewScenario.EMPTY) { now }.subscriptions().isEmpty())
    }
    @Test fun `five checkpoints reject a sixth without losing selection`() = runTest {
        val client = PreviewAppClient(PreviewScenario.FIVE_CHECKPOINTS) { now }
        assertEquals(5, client.subscriptions().size)
        try { client.setSubscription(7, true, true); fail("sixth must be rejected") }
        catch (_: IllegalStateException) { }
        assertEquals(listOf(17, 6, 1, 29, 5), client.subscriptions().map { it.checkpoint_id })
    }
    @Test fun `forecast and fact have separate kinds with future expiry`() = runTest {
        val client = PreviewAppClient(PreviewScenario.FORECAST) { now }
        val forecast = client.subscriptions().single().alerts.single()
        assertEquals("surge_forecast", forecast.kind)
        assertEquals("2026-10-06T10:00:00Z", forecast.expires_at)
        client.setScenario(PreviewScenario.FACT)
        assertEquals("surge_started", client.subscriptions().single().alerts.single().kind)
    }
    @Test fun `offline rejects reads and explicit reset restores fixture`() = runTest {
        val client = PreviewAppClient(PreviewScenario.FIVE_CHECKPOINTS) { now }
        client.setScenario(PreviewScenario.OFFLINE)
        try { client.checkpoints(); fail("offline read") } catch (_: IllegalStateException) { }
        client.setScenario(PreviewScenario.FIVE_CHECKPOINTS)
        client.removeSubscription(6)
        assertEquals(listOf(17, 1, 29, 5), client.subscriptions().map { it.checkpoint_id })
        client.setScenario(PreviewScenario.FIVE_CHECKPOINTS)
        assertEquals(5, client.subscriptions().size)
    }
    @Test fun `unsupported forecast remains fact capable`() = runTest {
        val client = PreviewAppClient(PreviewScenario.FORECAST_UNAVAILABLE) { now }
        val cp = client.checkpoints().first()
        assertFalse(cp.forecast_supported)
        assertTrue(cp.fact_supported)
    }
}
