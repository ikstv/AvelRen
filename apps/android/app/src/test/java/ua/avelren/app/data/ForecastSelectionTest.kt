package ua.avelren.app.data

import org.junit.Assert.*
import org.junit.Test

class ForecastSelectionTest {
    @Test fun sixthCheckpointIsRejectedAndExistingSelectionPreserved() {
        val five = listOf(1, 2, 3, 4, 5)
        assertEquals(five, ForecastSelection.add(five, 6))
    }
    @Test fun duplicateDoesNotConsumeAnotherSlot() {
        assertEquals(listOf(1, 2), ForecastSelection.add(listOf(1, 2), 2))
    }
    @Test fun removingOneAllowsAnotherCheckpoint() {
        val removed = ForecastSelection.remove(listOf(1, 2, 3, 4, 5), 3)
        assertEquals(listOf(1, 2, 4, 5, 6), ForecastSelection.add(removed, 6))
    }
    @Test fun storedSelectionDropsInvalidIdsDuplicatesAndExtraEntries() {
        assertEquals(listOf(17, 8, 9, 12, 5), ForecastSelection.parse("17,8,8,-1,no,9,12,5,6"))
        assertEquals(emptyList<Int>(), ForecastSelection.parse(null))
    }
}
