package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.DataRecency
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.avelren

@Composable
internal fun FullTestDataStatus(info: DataRecency.Info, refreshing: Boolean, onRefresh: () -> Unit) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        border = BorderStroke(1.dp, MaterialTheme.avelren.line)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(info.title, color = if (info.attention) AppAccent else AppInk,
                style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Bold)
            Text(info.detail, color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
            TextButton(enabled = !refreshing, onClick = onRefresh, modifier = Modifier.heightIn(min = 48.dp)) {
                Text(if (refreshing) "Оновлюємо…" else "Оновити дані")
            }
        }
    }
}
