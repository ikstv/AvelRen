package ua.avelren.app.data

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/**
 * Unit tests of the pure live-refresh logic (AND-4): freshness, keep-last-on-error
 * and the polling loop. The Compose wrapper (repeatOnLifecycle) is not tested here
 * — only the logic it drives.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveRefreshTest {

    private val now: Instant = Instant.parse("2026-08-07T12:00:00Z")

    // --- freshness --------------------------------------------------------

    @Test
    fun `recent observation is fresh`() {
        val f = LiveRefresh.freshness("2026-08-07T11:59:30Z", now)  // 30 s ago
        assertFalse(f.stale)
        assertEquals("щойно", f.label)
    }

    @Test
    fun `observation within threshold shows minutes and not stale`() {
        val f = LiveRefresh.freshness("2026-08-07T11:58:30Z", now)  // 90 s
        assertFalse(f.stale)
        assertEquals("1 хв тому", f.label)
    }

    @Test
    fun `observation past 180s threshold is stale`() {
        val f = LiveRefresh.freshness("2026-08-07T11:56:40Z", now)  // 200 s
        assertTrue(f.stale)
    }

    @Test
    fun `null observation time is stale and unknown`() {
        val f = LiveRefresh.freshness(null, now)
        assertTrue(f.stale)
    }

    // --- keep-last-on-error ----------------------------------------------

    @Test
    fun `keepOnError takes new value on success`() {
        assertEquals(listOf("new"), LiveRefresh.keepOnError(listOf("old"), Result.success(listOf("new"))))
    }

    @Test
    fun `keepOnError keeps previous on failure`() {
        val prev = listOf("old")
        val kept = LiveRefresh.keepOnError(prev, Result.failure(RuntimeException("net")))
        assertEquals(prev, kept)  // NOT an empty list
    }

    @Test
    fun `keepOnError surfaces data on first success after failure`() {
        val appeared = LiveRefresh.keepOnError(emptyList<String>(), Result.success(listOf("data")))
        assertEquals(listOf("data"), appeared)
    }

    @Test
    fun `partial failure keeps workload but updates forecast independently`() {
        var workload = listOf("wl-old")
        var forecast: String? = "fc-old"
        // One refresh pass: workload failed, forecast succeeded.
        workload = LiveRefresh.keepOnError(workload, Result.failure(RuntimeException()))
        forecast = LiveRefresh.keepOnError(forecast, Result.success("fc-new"))
        assertEquals(listOf("wl-old"), workload)  // not erased
        assertEquals("fc-new", forecast)          // updated despite the workload failure
    }

    // --- B2: freshness advances with the clock even for an unchanged snapshot ---

    @Test
    fun `stale flips as clock advances for unchanged observation`() {
        val obs = "2026-08-07T12:00:00Z"  // the same observation snapshot
        assertFalse(LiveRefresh.freshness(obs, Instant.parse("2026-08-07T12:00:30Z")).stale)  // 30 c
        assertFalse(LiveRefresh.freshness(obs, Instant.parse("2026-08-07T12:02:00Z")).stale)  // 120 c
        assertTrue(LiveRefresh.freshness(obs, Instant.parse("2026-08-07T12:03:30Z")).stale)   // 210 c
    }

    // --- B1: forecast keep-last is bound specifically to the selected checkpoint -----------

    private fun forecast(cp: Int) = Api.Forecast(
        checkpoint_id = cp, status = "ready", weeks_collected = 4.0, weeks_needed = 4,
    )

    @Test
    fun `scopedForecast drops previous checkpoint on failure of new one`() {
        // Cache for A, B is selected, the forecast(B) request failed → we do NOT show A's forecast.
        val kept = LiveRefresh.scopedForecast(
            previous = forecast(cp = 1),
            attempt = Result.failure(RuntimeException("slow/fail")),
            selectedCheckpoint = 2,
        )
        assertEquals(null, kept)
    }

    @Test
    fun `scopedForecast takes new forecast on success`() {
        val kept = LiveRefresh.scopedForecast(
            previous = forecast(cp = 1),
            attempt = Result.success(forecast(cp = 2)),
            selectedCheckpoint = 2,
        )
        assertEquals(2, kept?.checkpoint_id)
    }

    @Test
    fun `scopedForecast keeps previous when same checkpoint and request fails`() {
        val kept = LiveRefresh.scopedForecast(
            previous = forecast(cp = 2),
            attempt = Result.failure(RuntimeException("net")),
            selectedCheckpoint = 2,
        )
        assertEquals(2, kept?.checkpoint_id)  // the same checkpoint — the cached value is valid
    }

    // --- polling ----------------------------------------------------------

    @Test
    fun `poll refreshes immediately without waiting`() = runTest {
        var n = 0
        val job = launch { LiveRefresh.poll(60_000) { n++ } }
        runCurrent()
        assertEquals(1, n)  // immediately, without the 60-s wait
        job.cancel()
    }

    @Test
    fun `poll repeats every interval`() = runTest {
        var n = 0
        val job = launch { LiveRefresh.poll(60_000) { n++ } }
        runCurrent()
        assertEquals(1, n)
        advanceTimeBy(60_000); runCurrent()
        assertEquals(2, n)
        advanceTimeBy(60_000); runCurrent()
        assertEquals(3, n)
        job.cancel()
    }

    @Test
    fun `poll cancellation stops further refreshes`() = runTest {
        var n = 0
        val job = launch { LiveRefresh.poll(60_000) { n++ } }
        runCurrent()
        assertEquals(1, n)
        job.cancel()
        advanceTimeBy(180_000); runCurrent()
        assertEquals(1, n)  // after cancel — no refreshes at all
    }
}
