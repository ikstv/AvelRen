package ua.avelren.app.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

val LocalAvelRenColors = staticCompositionLocalOf { LightAvelRenColors }

/** Токени ROAD SIGN поза Material `ColorScheme` (сигнальні кольори, окантовка, нейтралі за роллю). */
val MaterialTheme.avelren: AvelRenColors
    @Composable get() = LocalAvelRenColors.current

// --- ROAD SIGN форми: панелі-знаки 10dp, картки 12dp, таблички-plate 6dp ---
object RoadSignShape {
    val Card: Shape = RoundedCornerShape(12.dp)
    val Plate: Shape = RoundedCornerShape(6.dp)
}

val PlateBorderWidth: Dp = 2.dp

private val RoadSignShapes = Shapes(
    extraSmall = RoundedCornerShape(6.dp),
    small = RoundedCornerShape(6.dp),
    medium = RoundedCornerShape(12.dp),
    large = RoundedCornerShape(10.dp),
    extraLarge = RoundedCornerShape(10.dp),
)

/** Тема слідує системній — власного перемикача застосунок не має. */
@Composable
fun AvelRenTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
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

/** Рамка таблички (номер черги тощо) — одинарна лінія 2dp, 6dp кут. */
fun Modifier.plateBorder(color: Color): Modifier =
    this.border(PlateBorderWidth, color, RoadSignShape.Plate)

/**
 * Тап без Material-ripple.
 *
 * Макет — HTML із `cursor:pointer`: підсвітки при натисканні немає ніде. А
 * дефолтний `clickable()` малює хвилю по ПРЯМОКУТНИХ межах composable, а не
 * по формі елемента — на `fillMaxWidth()`-рядку («ОЗНАЙОМИВСЯ») це біла смуга
 * через увесь екран, на дрібному тексті («ЗМІНИТИ», «✕») — прямокутна пляма
 * навколо гліфів.
 *
 * Зворотний зв'язок ніде не втрачається: кожна така дія одразу змінює стан —
 * чекбокс заповнюється, чип зеленіє, sheet закривається, рядок зникає.
 *
 * Кнопки (`Button`) свою індикацію лишають — вона там обмежена формою і
 * доречна.
 */
@Composable
fun Modifier.tapNoRipple(enabled: Boolean = true, onClick: () -> Unit): Modifier = clickable(
    interactionSource = remember { MutableInteractionSource() },
    indication = null,
    enabled = enabled,
    onClick = onClick,
)
