package ua.avelren.app.ui

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

class TelemetryTimeLabelTest {
    private val now = Instant.parse("2026-10-07T21:30:00Z") // 08.10, 00:30 Kyiv

    @Test fun relativeDatesUseKyivCalendarNotUtcOrElapsedHours() {
        assertEquals("сьогодні о 00:10", telemetryTimeLabel(Instant.parse("2026-10-07T21:10:00Z"), now))
        assertEquals("вчора о 23:50", telemetryTimeLabel(Instant.parse("2026-10-07T20:50:00Z"), now))
        assertEquals("06.10 о 23:50", telemetryTimeLabel(Instant.parse("2026-10-06T20:50:00Z"), now))
    }

    @Test fun olderYearIsNotAmbiguous() {
        assertEquals("06.10.2025 о 23:50", telemetryTimeLabel(Instant.parse("2025-10-06T20:50:00Z"), now))
    }

    @Test fun yesterdayAcrossYearBoundaryAndWinterOffset() {
        assertEquals("вчора о 23:50", telemetryTimeLabel(Instant.parse("2025-12-31T21:50:00Z"),
            Instant.parse("2025-12-31T22:10:00Z")))
    }
}
