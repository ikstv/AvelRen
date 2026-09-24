package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate
import java.time.Instant

class ForecastPresentationTest {
    @Test
    fun `rolling day keeps tomorrow and excludes stale and distant points`() {
        val now = Instant.parse("2026-09-24T14:30:00Z")
        val points = listOf(
            point("2026-09-25T14:00:00Z", 90),
            point("2026-09-24T15:00:00Z", 20),
            point("2026-09-24T14:00:00Z", 200),
            point("2026-09-25T15:00:00Z", 300),
            point("invalid", 500),
        )
        val result = ForecastPresentation.next24Hours(points, now)
        assertEquals(listOf(20, 90), result.map { it.vehicles_expected })
        assertEquals(90, ForecastPresentation.peak(result)?.vehicles_expected)
    }

    @Test
    fun `rolling day is 24 elapsed hours across Kyiv clock changes`() {
        for (start in listOf("2026-03-28T21:00:00Z", "2026-10-24T20:00:00Z")) {
            val now = Instant.parse(start)
            val points = (0L..25L).map { point(now.plusSeconds(it * 3600).toString(), it.toInt()) }
            val result = ForecastPresentation.next24Hours(points, now)
            assertEquals(24, result.size)
            assertEquals(24, result.last().vehicles_expected)
        }
    }
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
