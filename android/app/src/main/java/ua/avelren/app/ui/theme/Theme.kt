package ua.avelren.app.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

enum class ThemeMode { SYSTEM, LIGHT, DARK }

val LocalAvelRenColors = staticCompositionLocalOf { LightAvelRenColors }

/** Токени ROAD SIGN поза Material `ColorScheme` (сигнальні кольори, окантовка, нейтралі за роллю). */
val MaterialTheme.avelren: AvelRenColors
    @Composable get() = LocalAvelRenColors.current

// --- ROAD SIGN форми: панелі-знаки 10dp, картки 12dp, таблички-plate 6dp ---
object RoadSignShape {
    val Panel: Shape = RoundedCornerShape(10.dp)
    val Card: Shape = RoundedCornerShape(12.dp)
    val Plate: Shape = RoundedCornerShape(6.dp)
}

val PanelFrameWidth: Dp = 3.dp
val PanelInnerBorderWidth: Dp = 2.dp
val PlateBorderWidth: Dp = 2.dp

private val RoadSignShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(6.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(10.dp),
    extraLarge = RoundedCornerShape(10.dp),
)

@Composable
fun AvelRenTheme(mode: ThemeMode, content: @Composable () -> Unit) {
    val dark = when (mode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    CompositionLocalProvider(
        LocalAvelRenColors provides if (dark) DarkAvelRenColors else LightAvelRenColors
    ) {
        MaterialTheme(
            colorScheme = if (dark) DarkColors else LightColors,
            typography = AvelRenTypography,
            shapes = RoadSignShapes,
            content = content,
        )
    }
}

/**
 * Панель-знак: подвійна окантовка, як у фізичного дорожнього знаку — зовнішня
 * рамка [frameColor] ([PanelFrameWidth]) впритул до внутрішньої лінії
 * [innerColor] ([PanelInnerBorderWidth]), заливка [fillColor] всередині.
 * Використовується для героя (обраний КПП), зеленої панелі онбордингу тощо.
 */
@Composable
fun SignPanel(
    fillColor: Color,
    frameColor: Color,
    innerColor: Color,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(16.dp),
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier
            .background(frameColor, RoadSignShape.Panel)
            .padding(PanelFrameWidth)
            .background(innerColor, RoadSignShape.Panel)
            .padding(PanelInnerBorderWidth)
            .background(fillColor, RoadSignShape.Panel)
            .padding(contentPadding),
        content = content,
    )
}

/** Рамка таблички (номер черги, "СТОП" тощо) — одинарна лінія 2dp, 6dp кут. */
fun Modifier.plateBorder(color: Color): Modifier =
    this.border(PlateBorderWidth, color, RoadSignShape.Plate)
