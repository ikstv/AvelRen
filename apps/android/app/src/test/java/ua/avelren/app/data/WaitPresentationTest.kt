package ua.avelren.app.data

import org.junit.Assert.*
import org.junit.Test

class WaitPresentationTest {
    @Test fun `missing and ambiguous legacy zero have no measured wait`() {
        for (estimate in listOf(Api.WaitEstimate("missing", null, null), Api.WaitEstimate("legacy_unknown", 0, null), Api.WaitEstimate("reported", null, null), Api.WaitEstimate("future", 3600, null))) {
            assertEquals("Оцінка очікування відсутня", WaitPresentation.label(estimate))
        }
        assertNull(WaitPresentation.label(null))
    }
    @Test fun `zero is reported and positive legacy is labelled historical`() {
        assertEquals("0 хв очікування", WaitPresentation.label(Api.WaitEstimate("reported", 0, null)))
        assertEquals("1 год 0 хв очікування · За історичними даними", WaitPresentation.label(Api.WaitEstimate("legacy_unknown", 3600, null)))
        assertEquals("2 дн 3 год 40 хв очікування", WaitPresentation.label(Api.WaitEstimate("reported", 186000, null)))
    }
    @Test fun `new absent ETA never falls back to legacy ETA`() {
        val legacy = Api.Workload(17, "Тест", vehicles_in_queue = 80, wait_time_seconds = 0, is_paused = false, entry_eta = "legacy")
        assertEquals("legacy", WaitPresentation.entryEta(legacy))
        assertNull(WaitPresentation.entryEta(legacy.copy(wait_estimate = Api.WaitEstimate("missing", null, null))))
        assertNull(WaitPresentation.entryEta(legacy.copy(wait_estimate = Api.WaitEstimate("reported", 0, null))))
        assertEquals("new", WaitPresentation.entryEta(legacy.copy(wait_estimate = Api.WaitEstimate("reported", 0, "new"))))
    }
}
