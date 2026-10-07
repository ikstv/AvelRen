package ua.avelren.app.ui

import android.view.HapticFeedbackConstants
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.size
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import ua.avelren.app.ui.theme.SignClosed

/** Спільне прибирання КПП: червоний ROAD SIGN, 48dp і зрозумілий TalkBack. */
@Composable
internal fun RemoveCheckpointButton(label: String, enabled: Boolean = true, onClick: () -> Unit) {
    val view = LocalView.current
    IconButton(
        onClick = {
            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
            onClick()
        },
        enabled = enabled,
        modifier = Modifier.size(48.dp),
    ) {
        Icon(Icons.Filled.Close, contentDescription = "Прибрати КПП: $label",
            tint = SignClosed.copy(alpha = if (enabled) 1f else 0.38f),
            modifier = Modifier.size(24.dp))
    }
}
