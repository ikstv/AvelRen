package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import ua.avelren.app.data.Api
import java.time.Instant

class HistoryChartDataTest {
    @Test fun `chart preserves elapsed time and separates missing intervals`() {
        val end = Instant.parse("2026-10-22T12:00:00Z")
        val points = listOf(
            Api.HistoryPoint("2026-10-21T12:00:00Z", 20),
            Api.HistoryPoint("2026-10-21T12:01:00Z", 21),
            Api.HistoryPoint("2026-10-22T00:00:00Z", 30),
            Api.HistoryPoint("invalid", 50),
        )
        val segments = historyChartSegments(points, end)
        assertEquals(2, segments.size)
        assertEquals(0f, segments[0][0].position, 0.0001f)
        assertEquals(0.5f, segments[1][0].position, 0.0001f)
        assertEquals(30, segments[1][0].vehicles)
    }
    @Test fun `time labels use Kyiv dates and the same 24 hour window`() {
        val labels = historyChartTimeLabels(Instant.parse("2026-10-22T12:00:00Z"))
        assertEquals(listOf("21.10 15:00", "21.10 21:00", "22.10 03:00", "22.10 09:00", "22.10 15:00"), labels)
    }

}
