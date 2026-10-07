package ua.avelren.app.ui

import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test
import ua.avelren.app.data.Api

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class ServerStatusPresentationTest {
    private val now = Instant.parse("2026-10-07T22:30:00Z")
    private fun sample(cpu: Double? = 37.0, stamp: String = "2026-10-07T22:29:00Z",
                       stale: Boolean = false) = Api.ServerCpuStatus(cpu, stamp, 1, stale)

    @Test fun zeroAndEndpointsRemainValidAcrossKyivMidnight() {
        for (cpu in listOf(0.0, 50.0, 100.0)) {
            val result = serverStatusPresentation(sample(cpu), now)
            assertEquals(cpu, result.percent!!, 0.001)
            assertEquals("08.10 о 01:29", result.measuredAt)
        }
    }

    @Test fun staleFutureInvalidAndNullNeverLookLikeZero() {
        val invalid = listOf(sample(null), sample(Double.NaN), sample(Double.POSITIVE_INFINITY),
            sample(-1.0), sample(101.0), sample(stale = true),
            sample(stamp = "2026-10-07T22:24:59Z"),
            sample(stamp = "2026-10-07T22:30:01Z"), sample(stamp = "invalid"),
            sample(stamp = "2026-10-07T22:29:00"), sample().copy(sample_seconds = 2))
        invalid.forEach { assertNull(serverStatusPresentation(it, now).percent) }
        assertNull(serverStatusPresentation(null, now).percent)
        assertEquals(37.0, serverStatusPresentation(sample(stamp = "2026-10-07T22:25:00Z"), now).percent!!, 0.001)
    }

    @Test fun parsesNullAndMissingFreshnessFailClosed() {
        val parsed = Json.decodeFromString<Api.ServerCpuStatus>(
            """{"cpu_percent":0,"measured_at":"2026-10-07T22:29:00Z","sample_seconds":1,"stale":false}""")
        assertEquals(0.0, serverStatusPresentation(parsed, now).percent!!, 0.001)
        val missing = Json.decodeFromString<Api.ServerCpuStatus>("""{"cpu_percent":null,"measured_at":null,"sample_seconds":null}""")
        assertNull(serverStatusPresentation(missing, now).percent)
    }

    @Test fun concurrentRefreshDoesNotDuplicateRequests() = runTest {
        val response = CompletableDeferred<Api.ServerCpuStatus>()
        var calls = 0
        val state = ServerCpuLoader { calls++; response.await() }
        val first = launch { state.refresh() }
        runCurrent()
        state.refresh()
        assertEquals(1, calls)
        assertTrue(state.busy)
        response.complete(sample())
        first.join()
        assertFalse(state.busy)
        assertEquals(37.0, state.status!!.cpu_percent!!, 0.001)
    }

    @Test fun failedManualRefreshMarksPreviousSnapshotUntrusted() = runTest {
        var fail = false
        val state = ServerCpuLoader { if (fail) error("offline") else sample() }
        state.refresh()
        fail = true
        state.refresh()
        assertNotNull(state.error)
        assertNull(serverStatusPresentation(state.status, now).percent)
        assertEquals("2026-10-07T22:29:00Z", state.status!!.measured_at)
        assertFalse(state.busy)
    }

    @Test fun cancellationPropagatesAndReleasesBusy() = runTest {
        val state = ServerCpuLoader { throw CancellationException("left screen") }
        try { state.refresh(); fail("Expected cancellation") }
        catch (_: CancellationException) { }
        assertFalse(state.busy)
        assertNull(state.error)
    }

    @Test fun stationaryScreenExpiresWithoutAnotherNetworkRequest() = runTest {
        var calls = 0
        val state = ServerCpuLoader { calls++; sample(stamp = "2026-10-07T22:30:00Z") }
        state.refresh()
        val expiry = launch { state.expireSnapshot { now.plusMillis(testScheduler.currentTime) } }
        runCurrent()
        advanceTimeBy(300_000)
        runCurrent()
        assertFalse(state.status!!.stale)
        advanceTimeBy(1)
        runCurrent()
        assertTrue(state.status!!.stale)
        assertEquals(1, calls)
        expiry.join()
    }
}
