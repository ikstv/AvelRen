package ua.avelren.app.data

import java.time.Instant
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class ServerStatusTest {
    private val now = Instant.parse("2026-09-22T12:00:00Z")
    private val window = MaintenanceWindow(now.toString(), now.plusSeconds(180).toString())

    private fun status(
        internet: InternetState = InternetState.ONLINE,
        success: Boolean? = true,
        stale: Boolean? = false,
        maintenance: MaintenanceWindow? = null,
        time: Instant = now,
    ) = ServerStatus.resolve(internet, success, stale, maintenance, time)

    @Test fun offlineWinsOverCachedOnlineAndMaintenance() {
        assertEquals(ServerStatus.NO_INTERNET, status(InternetState.OFFLINE, maintenance = window))
    }

    @Test fun bannerHasTheAgreedVisibleStatesIncludingPlannedRestart() {
        assertEquals(
            setOf(
                "СЕРВЕР ОНЛАЙН",
                "НЕМАЄ ІНТЕРНЕТУ",
                "СЛАБКИЙ ІНТЕРНЕТ",
                "ТЕХНІЧНІ РОБОТИ",
                "ПЕРЕЗАПУСК СЕРВЕРА",
            ),
            ServerStatus.entries.map { it.label }.filter { it.isNotEmpty() }.toSet(),
        )
    }

    @Test fun disconnectDoesNotShowAnIntermediateConnectionMessage() {
        assertEquals("", status(InternetState.UNKNOWN, false).label)
        assertEquals("НЕМАЄ ІНТЕРНЕТУ", status(InternetState.OFFLINE, false).label)
        assertEquals("", status(InternetState.ONLINE, null).label)
        assertEquals("СЕРВЕР ОНЛАЙН", status(InternetState.ONLINE, true).label)
    }

    @Test fun responseFailureIsNotLossOfInternet() {
        assertEquals(ServerStatus.UNREACHABLE, status(success = false))
        assertEquals(ServerStatus.CONNECTION_UNKNOWN, status(InternetState.UNKNOWN, false))
    }

    @Test fun initialAndEmptyDataNeverClaimOnline() {
        assertEquals(ServerStatus.CHECKING, status(success = null))
        assertEquals(ServerStatus.NO_DATA, status(stale = null))
    }

    @Test fun staleDataNeverMeansReboot() {
        assertEquals(ServerStatus.STALE, status(stale = true))
        assertEquals(ServerStatus.ONLINE, status())
    }

    @Test fun checkingIsHiddenAndWeakSignalRequiresMeasurement() {
        assertEquals("", ServerStatus.CHECKING.label)
        assertEquals(ServerStatus.WEAK_INTERNET, status(InternetState.WEAK))
        assertEquals(ServerStatus.UNREACHABLE, status(InternetState.ONLINE, false))
        assertEquals(ServerStatus.NO_INTERNET, status(InternetState.OFFLINE, false))
        assertTrue(NetworkAvailability.weakWifiSignal(true, -90))
        assertFalse(NetworkAvailability.weakWifiSignal(true, -60))
        assertFalse(NetworkAvailability.weakWifiSignal(true, Int.MIN_VALUE))
        assertFalse(NetworkAvailability.weakWifiSignal(true, -127))
        assertFalse(NetworkAvailability.weakWifiSignal(false, -90))
        assertFalse(NetworkAvailability.weakWifiSignal(true, null))
    }

    @Test fun instabilityNeedsRepeatedActualLossAndClearsAfterStableMinute() {
        val tracker = ConnectionStability()
        assertEquals(InternetState.ONLINE, tracker.observe(InternetState.ONLINE, 0))
        assertEquals(InternetState.OFFLINE, tracker.observe(InternetState.OFFLINE, 1_000))
        assertEquals(InternetState.ONLINE, tracker.observe(InternetState.ONLINE, 2_000))
        assertEquals(InternetState.OFFLINE, tracker.observe(InternetState.OFFLINE, 3_000))
        assertEquals(InternetState.WEAK, tracker.observe(InternetState.ONLINE, 4_000))
        assertEquals(InternetState.ONLINE, tracker.observe(InternetState.ONLINE, 64_000))
    }

    @Test fun confirmedWindowBecomesRestartWhenServerStopsAnswering() {
        assertEquals(ServerStatus.MAINTENANCE, status(success = true, maintenance = window))
        assertEquals(ServerStatus.RESTARTING, status(success = false, maintenance = window))
        assertEquals(3L, window.remainingMinutes(now))
        assertEquals(1L, window.remainingMinutes(now.plusSeconds(179)))
        assertEquals(ServerStatus.UNREACHABLE, status(success = false, maintenance = window, time = now.plusSeconds(180)))
        assertNull(window.remainingMinutes(now.plusSeconds(180)))
    }

    @Test fun futureWindowDoesNotSayWorkHasStarted() {
        assertEquals(ServerStatus.ONLINE, status(maintenance = window, time = now.minusSeconds(1)))
    }

    @Test fun invalidWindowsAreIgnored() {
        listOf(
            MaintenanceWindow("invalid", now.toString()),
            MaintenanceWindow(now.toString(), now.minusSeconds(1).toString()),
            MaintenanceWindow(now.toString(), now.plusSeconds(901).toString()),
            MaintenanceWindow(now.plusSeconds(86401).toString(), now.plusSeconds(86500).toString()),
        ).forEach { assertEquals(ServerStatus.ONLINE, status(maintenance = it)) }
    }

    @Test fun publicContractAndUnknownFieldsAreCompatible() {
        val json = Json { ignoreUnknownKeys = true }
        val result = json.decodeFromString<PublicServerStatus>(
            """{"maintenance":{"starts_at":"2026-09-22T12:00:00+00:00","ends_at":"2026-09-22T12:03:00+00:00"},"future":true}"""
        )
        assertEquals(ServerStatus.MAINTENANCE, status(maintenance = result.maintenance))
        assertNull(json.decodeFromString<PublicServerStatus>("{}").maintenance)
    }
}
