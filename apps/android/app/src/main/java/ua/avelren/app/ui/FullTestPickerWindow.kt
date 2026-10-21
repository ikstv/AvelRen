package ua.avelren.app.ui

import android.graphics.Color as AndroidColor
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.ThemeChoice

/** Window chrome for the two gated FullTest full-screen checkpoint pickers. */
@Composable
internal fun FullTestPickerWindowChrome() {
    val view = LocalView.current
    val dark = LocalThemeChoice.current != ThemeChoice.LIGHT
    DisposableEffect(view, dark) {
        (view.parent as? DialogWindowProvider)?.window?.let { window ->
            window.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            window.setDimAmount(0f)
            @Suppress("DEPRECATION")
            window.statusBarColor = AndroidColor.TRANSPARENT
            @Suppress("DEPRECATION")
            window.navigationBarColor = AndroidColor.TRANSPARENT
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !dark
                isAppearanceLightNavigationBars = !dark
            }
        }
        // Only this dialog's window is changed; it is disposed with the picker.
        onDispose { }
    }
}
