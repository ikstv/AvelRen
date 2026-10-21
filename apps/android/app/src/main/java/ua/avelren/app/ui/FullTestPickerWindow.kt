package ua.avelren.app.ui

import android.graphics.Color as AndroidColor
import android.os.Build
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.ThemeChoice

/** Native bounds and window chrome for gated FullTest dialogs and pickers. */
@Composable
internal fun FullTestPickerWindowChrome(preserveDim: Boolean = false) {
    val view = LocalView.current
    val dark = LocalThemeChoice.current != ThemeChoice.LIGHT
    DisposableEffect(view, dark, preserveDim) {
        (view.parent as? DialogWindowProvider)?.window?.let { window ->
            if (!preserveDim) {
                window.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
                window.setDimAmount(0f)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                // Floating dialogs keep DEFAULT cutout handling even on Android 15.
                // Cover the landscape cutout strip; caller safeDrawing still keeps
                // labels and touch targets outside it.
                window.attributes = window.attributes.apply {
                    layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                }
            }
            // Keep usePlatformDefaultWidth=true in callers: Compose 1.7's
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
        // Only this dialog's window is changed; it is disposed with the dialog.
        onDispose { }
    }
}
