package ua.avelren.app.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

// ROAD SIGN design system — сигнальна семантика дорожнього знаку, перенесена
// в UI: зелений = «їдь» (панель героя), жовтий = «увага / росте», червоний =
// «закрито / призупинено», синій = дані (майбутні графіки). Панелі-знаки
// мають подвійну окантовку, як фізичний дорожній знак: зовнішня рамка (frame)
// + внутрішня темніша лінія того самого сигнального кольору.

// --- Сигнальні кольори: однакові в обох темах — це семантика, а не оздоба ---
val SignGo = Color(0xFF0E7A4E)
val SignGoDeep = Color(0xFF0A5F3D)
val SignOnGo = Color(0xFFFFFFFF)
val SignWarn = Color(0xFFF5C400)
val SignOnWarn = Color(0xFF231F00)
val SignClosed = Color(0xFFD5382C)
val SignOnClosed = Color(0xFFFFFFFF)

// --- Нейтральні: світла (день) ---
val PaperLight = Color(0xFFF4F5F3)
val InkLight = Color(0xFF1C1E20)
val Ink2Light = Color(0xFF5B6065)
val LineLight = Color(0xFFD9DCD8)
val PanelLight = Color(0xFFFFFFFF)
val FrameLight = Color(0xFFFFFFFF)
val DataLight = Color(0xFF0B5FA5)

// --- Нейтральні: темна (ніч у кабіні) ---
val PaperDark = Color(0xFF16181A)
val InkDark = Color(0xFFF2F4F1)
val Ink2Dark = Color(0xFF9AA0A6)
val LineDark = Color(0xFF2A2E31)
val PanelDark = Color(0xFF1F2224)
val FrameDark = Color(0xFFE8ECE8)
val DataDark = Color(0xFF4C97DB)

/**
 * Токени ROAD SIGN, недоступні через Material `ColorScheme` (сигнальні
 * кольори з on-* парами, окантовка знаків, нейтралі за іменем ролі, а не
 * Material-слотом). Дістаються через `MaterialTheme.avelren`.
 */
data class AvelRenColors(
    val paper: Color,
    val ink: Color,
    val ink2: Color,
    val line: Color,
    val panel: Color,
    val frame: Color,
    val go: Color,
    val goDeep: Color,
    val onGo: Color,
    val warn: Color,
    val onWarn: Color,
    val closed: Color,
    val onClosed: Color,
    val data: Color,
    val dark: Boolean,
)

val LightAvelRenColors = AvelRenColors(
    paper = PaperLight,
    ink = InkLight,
    ink2 = Ink2Light,
    line = LineLight,
    panel = PanelLight,
    frame = FrameLight,
    go = SignGo,
    goDeep = SignGoDeep,
    onGo = SignOnGo,
    warn = SignWarn,
    onWarn = SignOnWarn,
    closed = SignClosed,
    onClosed = SignOnClosed,
    data = DataLight,
    dark = false,
)

val DarkAvelRenColors = AvelRenColors(
    paper = PaperDark,
    ink = InkDark,
    ink2 = Ink2Dark,
    line = LineDark,
    panel = PanelDark,
    frame = FrameDark,
    go = SignGo,
    goDeep = SignGoDeep,
    onGo = SignOnGo,
    warn = SignWarn,
    onWarn = SignOnWarn,
    closed = SignClosed,
    onClosed = SignOnClosed,
    data = DataDark,
    dark = true,
)

// Material `ColorScheme` — для компонентів, що його очікують напряму
// (TextField, DatePicker/TimePicker у EtaTargetDialog тощо). Мапиться на ті
// самі токени, щоб системні компоненти не випадали з палітри.
val LightColors: ColorScheme = lightColorScheme(
    primary = SignGo,
    onPrimary = SignOnGo,
    background = PaperLight,
    onBackground = InkLight,
    surface = PanelLight,
    onSurface = InkLight,
    surfaceVariant = PaperLight,
    onSurfaceVariant = Ink2Light,
    outline = LineLight,
    error = SignClosed,
    onError = SignOnClosed,
)

val DarkColors: ColorScheme = darkColorScheme(
    primary = SignGo,
    onPrimary = SignOnGo,
    background = PaperDark,
    onBackground = InkDark,
    surface = PanelDark,
    onSurface = InkDark,
    surfaceVariant = PaperDark,
    onSurfaceVariant = Ink2Dark,
    outline = LineDark,
    error = SignClosed,
    onError = SignOnClosed,
)
