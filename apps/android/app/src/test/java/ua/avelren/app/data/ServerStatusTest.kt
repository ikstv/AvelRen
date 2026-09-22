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

    @Test fun confirmedWindowSurvivesFailedRequestButExpires() {
        assertEquals(ServerStatus.MAINTENANCE, status(success = false, maintenance = window))
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
