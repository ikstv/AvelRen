package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Test

class FavoriteCheckpointsTest {
    @Test fun parsingRejectsMalformedAndDuplicateIdsWithoutLimitingFavorites() {
        assertEquals(listOf(17, 8, 9, 12, 5, 6), FavoriteCheckpoints.parse("17,8,8,-1,no,9,0,12,5,6,2147483648"))
        assertEquals(emptyList<Int>(), FavoriteCheckpoints.parse(null))
    }

    @Test fun togglingAddsAtEndAndRemovesOnlyRequestedId() {
        assertEquals(listOf(4, 8, 9), FavoriteCheckpoints.toggle(listOf(4, 8), 9))
        assertEquals(listOf(4, 9), FavoriteCheckpoints.toggle(listOf(4, 8, 9), 8))
        assertEquals(listOf(4), FavoriteCheckpoints.toggle(listOf(4, 4, -1), 0))
    }

    @Test fun pickerKeepsAllRowsAndSourceOrderWithinGroups() {
        assertEquals(listOf(3, 2, 1, 4), FavoriteCheckpoints.orderedForPicker(listOf(1, 3, 4, 2), listOf(2, 3, 99)) { it })
    }

    @Test fun unavailableFavoritesSurviveTogglingAndPickerFiltering() {
        val saved = listOf(99, 3)
        assertEquals(listOf(3, 1), FavoriteCheckpoints.orderedForPicker(listOf(1, 3), saved) { it })
        assertEquals(listOf(99, 3, 1), FavoriteCheckpoints.toggle(saved, 1))
        assertEquals(listOf(99, 3), saved)
    }
}
