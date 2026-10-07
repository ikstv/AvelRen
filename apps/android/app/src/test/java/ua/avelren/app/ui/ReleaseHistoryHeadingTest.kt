package ua.avelren.app.ui

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Test

class ReleaseHistoryHeadingTest {
    @Test fun unpublishedVersionDoesNotInventReleaseDate() {
        assertEquals("Версія 0.1.3 · у підготовці", releaseHistoryHeading("0.1.3", null))
    }

    @Test fun publishedVersionHasUkrainianDayMonthAndYear() {
        assertEquals("Версія 0.1.2 · 26 вересня 2026 року",
            releaseHistoryHeading("0.1.2", Instant.parse("2026-09-26T01:16:12Z")))
    }

    @Test fun publicationNearMidnightUsesKyivCalendarDate() {
        assertEquals("Версія 9.0.0 · 1 жовтня 2026 року",
            releaseHistoryHeading("9.0.0", Instant.parse("2026-09-30T23:30:00Z")))
    }
}
