package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FullTestCheckpointLabelTest {
    @Test fun separatesVehicleCategoryWithoutRemovingCheckpointParentheses() {
        val result = fullTestCheckpointLabel("🇭🇺 Чоп (Тиса) – Захонь (для вантажівок ≥ 3,5 тонн)")
        assertEquals("🇭🇺 Чоп (Тиса) – Захонь", result.name)
        assertEquals("для вантажівок ≥ 3,5 тонн", result.vehicleCategory)
    }

    @Test fun preservesBothWeightBoundsAndSpecialCargoRestriction() {
        val result = fullTestCheckpointLabel(
            "Угринів – Долгобичув (для вантажівок ≥ 3,5 тонн до ≤ 7,5 тонн, товари групи 1)",
        )
        assertEquals("Угринів – Долгобичув", result.name)
        assertEquals("для вантажівок ≥ 3,5 тонн до ≤ 7,5 тонн, товари групи 1", result.vehicleCategory)
    }

    @Test fun splitsOnlyTheFinalVehicleQualifier() {
        val result = fullTestCheckpointLabel("КПП (для місцевого руху) – кордон (для вантажівок)")
        assertEquals("КПП (для місцевого руху) – кордон", result.name)
        assertEquals("для вантажівок", result.vehicleCategory)
    }

    @Test fun preservesWholeNameWhenThereIsNoSafeTrailingQualifier() {
        for (title in listOf(
            "Чоп (Тиса) – Захонь",
            "Чоп (Тиса)",
            "Чоп (для вантажівок",
            "Чоп (для вантажівок) – Захонь",
            " (для вантажівок)",
            "Чоп (для вантажівок) ",
            "",
        )) {
            val result = fullTestCheckpointLabel(title)
            assertEquals(title, result.name)
            assertNull(result.vehicleCategory)
        }
    }
}
