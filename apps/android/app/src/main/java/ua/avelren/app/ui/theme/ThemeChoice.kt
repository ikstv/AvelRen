package ua.avelren.app.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

enum class ThemeChoice {
    DARK, LIGHT;
    companion object {
        fun fromStored(value: String?): ThemeChoice = entries.firstOrNull { it.name == value } ?: DARK
    }
}

data class AppPalette(val background: Color, val ink: Color, val accent: Color, val onAccent: Color)
fun appPalette(choice: ThemeChoice): AppPalette = if (choice == ThemeChoice.LIGHT) {
    AppPalette(Color.White, InkLight, Color(0xFFB71C1C), Color.White)
} else {
    AppPalette(Color.Black, Color.White, SignWarn, SignOnWarn)
}
val LocalThemeChoice = staticCompositionLocalOf { ThemeChoice.DARK }
val AppBackground: Color @Composable get() = appPalette(LocalThemeChoice.current).background
val AppInk: Color @Composable get() = appPalette(LocalThemeChoice.current).ink
val AppAccent: Color @Composable get() = appPalette(LocalThemeChoice.current).accent
val AppOnAccent: Color @Composable get() = appPalette(LocalThemeChoice.current).onAccent
