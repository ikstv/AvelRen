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

/** Native bounds and window chrome for the two gated FullTest checkpoint pickers. */
@Composable
internal fun FullTestPickerWindowChrome() {
    val view = LocalView.current
    val dark = LocalThemeChoice.current != ThemeChoice.LIGHT
    DisposableEffect(view, dark) {
        (view.parent as? DialogWindowProvider)?.window?.let { window ->
            window.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            window.setDimAmount(0f)
            // Keep usePlatformDefaultWidth=true in both callers: Compose 1.7's
            // false branch derives both axes from Configuration on Android 15.
            // MATCH_PARENT gives full width while preserving native height limits.
            window.setLayout(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.MATCH_PARENT,
            )
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
