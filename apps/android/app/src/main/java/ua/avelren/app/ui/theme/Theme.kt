package ua.avelren.app.ui.theme

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import android.app.Activity
import android.view.HapticFeedbackConstants
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.runtime.getValue
import androidx.compose.runtime.SideEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.core.view.WindowCompat
import ua.avelren.app.BuildConfig
import ua.avelren.app.data.UiPrefs
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

/** Вибрана тема зберігається локально; початкова тема — чорна. */
@Composable
fun AvelRenTheme(content: @Composable () -> Unit) {
    val context = LocalContext.current
    val view = LocalView.current
    val theme by remember(context) { UiPrefs.themeFlow(context) }.collectAsStateWithLifecycle(ThemeChoice.DARK)
    val dark = theme == ThemeChoice.DARK
    val palette = appPalette(theme)
    val fullTestColors = if (BuildConfig.ENABLE_TEST_DRAWER) fullTestColorScheme(theme) else null
    if (!view.isInEditMode) {
        SideEffect {
            (context as? Activity)?.window?.let { window ->
                WindowCompat.getInsetsController(window, view).apply {
                    isAppearanceLightStatusBars = !dark
                    isAppearanceLightNavigationBars = !dark
                }
                @Suppress("DEPRECATION")
                window.statusBarColor = if (dark) android.graphics.Color.BLACK else android.graphics.Color.WHITE
                @Suppress("DEPRECATION")
                window.navigationBarColor = if (dark) android.graphics.Color.BLACK else android.graphics.Color.WHITE
            }
        }
    }
    CompositionLocalProvider(
        LocalThemeChoice provides theme,
        LocalAvelRenColors provides (if (dark) DarkAvelRenColors else LightAvelRenColors).copy(
            paper = palette.background, ink = palette.ink, panel = palette.background,
        ).let { colors ->
            if (fullTestColors != null) colors.copy(
                panel = fullTestColors.surfaceContainer,
                data = palette.accent,
            ) else colors
        }
    ) {
        MaterialTheme(
            colorScheme = fullTestColors ?: (if (dark) DarkColors else LightColors).copy(
                primary = palette.accent, onPrimary = palette.onAccent,
                background = palette.background, surface = palette.background,
                onBackground = palette.ink, onSurface = palette.ink,
            ),
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
    onClick = hapticClick(onClick),
)

/** Same system-respecting tick as bottom navigation, once per accepted action. */
@Composable
fun hapticClick(onClick: () -> Unit): () -> Unit {
    val view = LocalView.current
    return {
        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
        onClick()
    }
}

@Composable
fun Modifier.hapticClickable(enabled: Boolean = true, onClick: () -> Unit): Modifier =
    clickable(enabled = enabled, onClick = hapticClick(onClick))

@Composable
fun hapticToggle(onChange: (Boolean) -> Unit): (Boolean) -> Unit {
    val view = LocalView.current
    return { value ->
        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
        onChange(value)
    }
}
