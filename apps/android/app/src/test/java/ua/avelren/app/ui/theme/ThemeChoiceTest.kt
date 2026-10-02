package ua.avelren.app.ui.theme

import org.junit.Assert.*
import org.junit.Test
import androidx.compose.ui.graphics.toArgb

class ThemeChoiceTest {
    @Test fun missingOrUnknownPreferenceKeepsCurrentDarkTheme() {
        assertEquals(ThemeChoice.DARK, ThemeChoice.fromStored(null))
        assertEquals(ThemeChoice.DARK, ThemeChoice.fromStored("system"))
    }
    @Test fun bothChoicesRoundTripWithoutDependingOnSystemTheme() {
        ThemeChoice.entries.forEach { assertEquals(it, ThemeChoice.fromStored(it.name)) }
    }
    @Test fun lightThemeUsesReadableInkAndRedAccent() {
        val palette = appPalette(ThemeChoice.LIGHT)
        assertEquals(0xFFFFFFFF.toInt(), palette.background.toArgb())
        assertEquals(0xFF1C1E20.toInt(), palette.ink.toArgb())
        assertEquals(0xFFB71C1C.toInt(), palette.accent.toArgb())
        assertEquals(0xFFFFFFFF.toInt(), palette.onAccent.toArgb())
    }
    @Test fun darkThemePreservesOwnerColors() {
        val palette = appPalette(ThemeChoice.DARK)
        assertEquals(0xFF000000.toInt(), palette.background.toArgb())
        assertEquals(SignWarn, palette.accent)
    }
}
