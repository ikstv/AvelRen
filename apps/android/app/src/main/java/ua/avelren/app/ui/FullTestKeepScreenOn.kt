package ua.avelren.app.ui

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.view.WindowManager
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.platform.LocalContext

/** This FullTest preference is the sole owner of the activity's keep-screen flag. */
@Composable
internal fun FullTestKeepScreenOn(enabled: Boolean) {
    val window = LocalContext.current.activityOrNull()?.window
    DisposableEffect(window, enabled) {
        // Clear the client window flag explicitly: clearing View.keepScreenOn alone
        // can leave a window-level KEEP_SCREEN_ON request after window updates.
        if (enabled) window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }
}

private tailrec fun Context.activityOrNull(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> if (baseContext !== this) baseContext.activityOrNull() else null
    else -> null
}
