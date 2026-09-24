package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class ForecastPresentationTest {
    private fun point(time: String, vehicles: Int) = Api.ForecastPoint(
        time = time,
        wait_seconds_low = 0,
        wait_seconds_expected = 0,
        wait_seconds_high = 0,
        vehicles_low = 0,
        vehicles_expected = vehicles,
        vehicles_high = vehicles,
        samples = 8,
    )

    @Test
    fun `daily forecast uses Kyiv date across winter midnight`() {
        val points = listOf(
            point("2026-01-10T21:30:00Z", 12), // 23:30 in Kyiv
            point("2026-01-10T22:00:00Z", 99), // 00:00 next day in Kyiv
        )

        val today = ForecastPresentation.forKyivDate(points, LocalDate.parse("2026-01-10"))

        assertEquals(1, today.size)
        assertEquals(12, ForecastPresentation.peak(today)?.vehicles_expected)
    }

    @Test
    fun `daily forecast uses Kyiv date across summer midnight`() {
        val points = listOf(
            point("2026-06-01T20:59:00Z", 7), // 23:59 in Kyiv
            point("2026-06-01T21:00:00Z", 70), // 00:00 next day in Kyiv
        )

        val today = ForecastPresentation.forKyivDate(points, LocalDate.parse("2026-06-01"))

        assertEquals(1, today.size)
        assertEquals(7, ForecastPresentation.peak(today)?.vehicles_expected)
    }

    @Test
    fun `peak is absent when no hourly points are available`() {
        assertNull(ForecastPresentation.peak(emptyList()))
    }

    @Test
    fun `older forecast responses do not invent vehicle ranges`() {
        val legacy = Api.ForecastPoint(
            time = "2026-09-24T12:00:00Z",
            wait_seconds_low = 0,
            wait_seconds_expected = 0,
            wait_seconds_high = 0,
            vehicles_expected = 42,
        )

        assertNull(legacy.vehicles_low)
        assertNull(legacy.vehicles_high)
        assertNull(legacy.samples)
    }
}
