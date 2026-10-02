package ua.avelren.app.data

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class CountForecastPresentationTest {
    private fun point(time: String, vehicles: Int) = Api.CountForecastPoint(time, vehicles_low = null, vehicles_expected = vehicles, vehicles_high = null, calibration_samples = 8, wait_estimate = null)
    @Test fun `count only points use elapsed 24h across winter summer and DST`() {
        for (start in listOf("2026-01-10T21:30:00Z", "2026-06-01T20:30:00Z", "2026-03-28T21:00:00Z", "2026-10-24T20:00:00Z")) {
            val now = Instant.parse(start)
            val points = (25L downTo 0L).map { point(now.plusSeconds(it * 3600).toString(), it.toInt()) }
            val result = ForecastPresentation.next24CountHours(points + point("invalid", 500) + point(now.plusSeconds(3600).toString(), 900), now)
            assertEquals(24, result.size)
            assertEquals(1, result.first().vehicles_expected)
            assertEquals(24, ForecastPresentation.countPeak(result)?.vehicles_expected)
            assertTrue(result.all { it.wait_estimate == null })
        }
        assertNull(ForecastPresentation.countPeak(emptyList()))
    }
}
