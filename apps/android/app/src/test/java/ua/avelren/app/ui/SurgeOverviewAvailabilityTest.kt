package ua.avelren.app.ui

import org.junit.Assert.*
import org.junit.Test
import ua.avelren.app.data.SurgeCheckpoint
import ua.avelren.app.data.SurgeStatus

class SurgeOverviewAvailabilityTest {
    private val cp = SurgeCheckpoint(17, "Чоп", forecast_supported = true, data_fresh = true)
    @Test fun `snapshot failure never looks like verified fresh monitoring`() {
        assertNotNull(SurgePresentation.availabilityHint(cp, null))
    }
    @Test fun `stale checkpoint shows data problem even with valid forecast`() {
        assertNotNull(SurgePresentation.availabilityHint(cp.copy(data_fresh = false), SurgeStatus(17, "risk")))
    }
    @Test fun `unsupported forecast does not hide working factual monitoring`() {
        assertNull(SurgePresentation.availabilityHint(cp.copy(forecast_supported = false),
            SurgeStatus(17, "unavailable", reason = "unsupported")))
    }
    @Test fun `unavailable supported forecast and fresh normal monitoring differ`() {
        assertNotNull(SurgePresentation.availabilityHint(cp, SurgeStatus(17, "unavailable", reason = "stale")))
        assertNull(SurgePresentation.availabilityHint(cp, SurgeStatus(17, "no_signal")))
    }
}
