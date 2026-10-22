package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class EtaTimeOptionsTest {
    private val zone = ZoneId.of("Europe/Kyiv")

    @Test fun `today includes only hours strictly after now`() {
        val now = Instant.parse("2026-10-22T11:25:00Z")
        val hours = etaFutureHours(LocalDate.of(2026, 10, 22), now, zone)
        assertEquals((15..23).toList(), hours)
        assertFalse(etaTargetIsFuture(LocalDate.of(2026, 10, 22), 14, now, zone))
        assertTrue(etaTargetIsFuture(LocalDate.of(2026, 10, 22), 15, now, zone))
    }

    @Test fun `exact hour is past and tomorrow remains available at midnight`() {
        val now = Instant.parse("2026-10-22T20:00:00Z")
        assertEquals(emptyList<Int>(), etaFutureHours(LocalDate.of(2026, 10, 22), now, zone))
        assertEquals((0..23).toList(), etaFutureHours(LocalDate.of(2026, 10, 23), now, zone))
        assertFalse(etaTargetIsFuture(LocalDate.of(2026, 10, 22), 23, now, zone))
    }

    @Test fun `nonexistent daylight saving hour is not offered`() {
        val date = LocalDate.of(2026, 3, 29)
        val hours = etaFutureHours(date, Instant.parse("2026-03-28T20:00:00Z"), zone)
        assertFalse(hours.contains(3))
        assertTrue(hours.contains(4))
    }
}
