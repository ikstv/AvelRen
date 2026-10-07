package ua.avelren.app.data

import org.junit.Assert.*
import org.junit.Test

class ForecastSelectionTest {
    @Test fun fourthCheckpointIsRejectedAndExistingSelectionPreserved() {
        val three = listOf(1, 2, 3)
        assertEquals(three, ForecastSelection.add(three, 4))
    }
    @Test fun duplicateDoesNotConsumeAnotherSlot() {
        assertEquals(listOf(1, 2), ForecastSelection.add(listOf(1, 2), 2))
    }
    @Test fun removingOneAllowsAnotherCheckpoint() {
        val removed = ForecastSelection.remove(listOf(1, 2, 3), 3)
        assertEquals(listOf(1, 2, 6), ForecastSelection.add(removed, 6))
    }
    @Test fun storedSelectionDropsInvalidIdsDuplicatesAndExtraEntries() {
        assertEquals(listOf(17, 8, 9), ForecastSelection.parse("17,8,8,-1,no,9,12,5,6"))
        assertEquals(emptyList<Int>(), ForecastSelection.parse(null))
    }
}
