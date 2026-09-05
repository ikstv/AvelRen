package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Атрибуція джерела — вимога Google Play (Misleading Claims). Рядок мусить
 * лишатися непорожнім і НАЗИВАТИ джерело; посилання — на офіційний домен.
 * Тест ловить сценарій, коли хтось випадково спорожнить/зламає ці константи й
 * застосунок знову покаже держдані без атрибуції — привід для чергової відмови.
 */
class AttributionTest {
    @Test
    fun textNonEmptyAndNamesSource() {
        assertTrue(Attribution.TEXT.isNotBlank())
        assertTrue(
            "рядок атрибуції має називати джерело echerha.gov.ua",
            Attribution.TEXT.contains("echerha.gov.ua"),
        )
    }

    @Test
    fun linkPointsToOfficialSite() {
        assertEquals("https://echerha.gov.ua", Attribution.URL)
        assertTrue(Attribution.URL.startsWith("https://"))
    }
}
