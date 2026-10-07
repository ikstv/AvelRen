package ua.avelren.app.ui

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import ua.avelren.app.data.Api

class ResourceStatusPresentationTest {
    private val now = Instant.parse("2026-10-07T12:00:00Z")

    @Test fun zeroIsARealMeasurement() {
        val p = resourceStatusPresentation(Api.ServerResourceStatus(0, 1073741824,
            "2026-10-07T12:00:00Z", false), now, 300)
        assertEquals(0.0, p.percent!!, 0.0)
        assertEquals("0.0 / 1.0 ГіБ", p.amountLabel)
    }

    @Test fun trafficOverageFillsButKeepsRealPercent() {
        val p = resourceStatusPresentation(Api.ServerResourceStatus(1100000000, 1000000000,
            "2026-10-07T12:00:00Z", false, "2026-10"), now, 7200, true)
        assertEquals(110.0, p.percent!!, 0.001)
        assertEquals(1f, p.fillFraction)
        assertEquals("1.1 / 1.0 ГБ", p.amountLabel)
    }

    @Test fun missingStaleAndFutureAreUnavailable() {
        for (s in listOf(null,
            Api.ServerResourceStatus(1, 100, "2026-10-07T11:54:59Z", false),
            Api.ServerResourceStatus(1, 100, "2026-10-07T12:00:01Z", false),
            Api.ServerResourceStatus(101, 100, "2026-10-07T12:00:00Z", false))) {
            assertNull(resourceStatusPresentation(s, now, 300).percent)
        }
    }
}
