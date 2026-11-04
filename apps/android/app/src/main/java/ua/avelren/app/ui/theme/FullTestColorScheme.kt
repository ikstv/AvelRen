package ua.avelren.app.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.ui.graphics.Color

/** Усі ролі Material у FullTest використовують акценти AvelRen та нейтральні поверхні. */
internal fun fullTestColorScheme(theme: ThemeChoice): ColorScheme {
    val dark = theme == ThemeChoice.DARK
    val palette = appPalette(theme)
    val accentContainer = if (dark) Color(0xFF30290B) else Color(0xFFFCE7E5)
    val onAccentContainer = if (dark) palette.accent else Color(0xFF8C1212)
    val secondaryText = if (dark) Ink2Dark else Ink2Light
    val surface = if (dark) PaperDark else PaperLight

    return (if (dark) DarkColors else LightColors).copy(
        primary = palette.accent,
        onPrimary = palette.onAccent,
        primaryContainer = accentContainer,
        onPrimaryContainer = onAccentContainer,
        inversePrimary = appPalette(if (dark) ThemeChoice.LIGHT else ThemeChoice.DARK).accent,
        secondary = palette.accent,
        onSecondary = palette.onAccent,
        secondaryContainer = accentContainer,
        onSecondaryContainer = onAccentContainer,
        tertiary = palette.accent,
        onTertiary = palette.onAccent,
        tertiaryContainer = accentContainer,
        onTertiaryContainer = onAccentContainer,
        background = palette.background,
        onBackground = palette.ink,
        surface = palette.background,
        onSurface = palette.ink,
        surfaceVariant = surface,
        onSurfaceVariant = secondaryText,
        surfaceTint = Color.Transparent,
        inverseSurface = if (dark) PaperLight else PaperDark,
        inverseOnSurface = if (dark) InkLight else InkDark,
        error = if (dark) Color(0xFFFFB4AB) else Color(0xFFB3261E),
        onError = if (dark) Color(0xFF690005) else Color.White,
        errorContainer = if (dark) Color(0xFF421A18) else Color(0xFFF9DEDC),
        onErrorContainer = if (dark) Color(0xFFFFDAD6) else Color(0xFF410E0B),
        outline = if (dark) Color(0xFF777D82) else Color(0xFF777D77),
        outlineVariant = if (dark) LineDark else LineLight,
        scrim = Color.Black,
        surfaceBright = if (dark) Color(0xFF303437) else Color.White,
        surfaceDim = if (dark) Color.Black else Color(0xFFE0E3DE),
        surfaceContainerLowest = palette.background,
        surfaceContainerLow = if (dark) Color(0xFF101214) else Color(0xFFFAFAF9),
        surfaceContainer = surface,
        surfaceContainerHigh = if (dark) PanelDark else Color(0xFFECEEEB),
        surfaceContainerHighest = if (dark) Color(0xFF282C2F) else Color(0xFFE4E7E3),
    )
}
