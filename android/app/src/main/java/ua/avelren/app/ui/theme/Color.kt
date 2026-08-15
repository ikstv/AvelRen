package ua.avelren.app.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// Modernist design system — mono scheme, single red accent, inverted ground.
// Tokens from the design handoff (§1).

val AvelRedLight = Color(0xFFEC3013)
val AvelRedDark = Color(0xFFFF563C)

// Extra brand tokens not covered by Material's ColorScheme, exposed via
// LocalAvelRenColors so screens can reach the accent-tint / muted / flag roles.
data class AvelRenColors(
    val accentTint: Color,
    val accentOnTint: Color,
    val muted: Color,
    val flagTagBg: Color,
    val flagTagText: Color,
    val dark: Boolean,
)

val LightColors: ColorScheme = lightColorScheme(
    primary = AvelRedLight,
    onPrimary = Color(0xFFF3F2F2),
    background = Color(0xFFF3F2F2),
    onBackground = Color(0xFF201E1D),
    surface = Color(0xFFEAE9E9),
    onSurface = Color(0xFF201E1D),
    surfaceVariant = Color(0xFFFBF8F1),
    onSurfaceVariant = Color(0xFF605D5D),
    outline = Color(0x66201E1D),
    error = AvelRedLight,
    onError = Color(0xFFF3F2F2),
)

val DarkColors: ColorScheme = darkColorScheme(
    primary = AvelRedDark,
    onPrimary = Color(0xFF1A1817),
    background = Color(0xFF1A1817),
    onBackground = Color(0xFFF3F2F2),
    surface = Color(0xFF262220),
    onSurface = Color(0xFFF3F2F2),
    surfaceVariant = Color(0xFF262220),
    onSurfaceVariant = Color(0xFFC4BFBC),
    outline = Color(0x47F3F2F2),
    error = AvelRedDark,
    onError = Color(0xFF1A1817),
)

val LightAvelRenColors = AvelRenColors(
    accentTint = Color(0xFFFFF2EF),
    accentOnTint = Color(0xFF7C1405),
    muted = Color(0xFF7D7979),
    flagTagBg = Color(0xFFEAE7E7),
    flagTagText = Color(0xFF444141),
    dark = false,
)

val DarkAvelRenColors = AvelRenColors(
    accentTint = Color(0xFF3A1A12),
    accentOnTint = Color(0xFFFFC4B8),
    muted = Color(0xFFA8A3A0),
    flagTagBg = Color(0xFF33302D),
    flagTagText = Color(0xFFDCD8D5),
    dark = true,
)
