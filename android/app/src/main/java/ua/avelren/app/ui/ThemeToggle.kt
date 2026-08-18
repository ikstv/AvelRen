package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.ui.theme.ThemeMode

/** Modernist segmented control: Light | Dark. 0dp, 2dp rule, uppercase. */
@Composable
fun ThemeToggle(mode: ThemeMode, onChange: (ThemeMode) -> Unit) {
    Row(
        Modifier.border(2.dp, MaterialTheme.colorScheme.outline)
    ) {
        listOf(ThemeMode.LIGHT to "Світла", ThemeMode.DARK to "Темна").forEach { (m, label) ->
            val active = mode == m
            Text(
                text = label.uppercase(),
                modifier = Modifier
                    .clickable { onChange(m) }
                    .background(if (active) MaterialTheme.colorScheme.primary else Color.Transparent)
                    .padding(horizontal = 16.dp, vertical = 9.dp),
                color = if (active) MaterialTheme.colorScheme.onPrimary
                else MaterialTheme.colorScheme.onBackground,
                fontWeight = FontWeight.ExtraBold,
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}
