package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.ui.theme.RoadSignShape
import ua.avelren.app.ui.theme.ThemeMode
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.plateBorder

/** ROAD SIGN plate-перемикач: Світла | Темна. Викликається з меню за іконкою теми в шапці. */
@Composable
fun ThemeToggle(mode: ThemeMode, onChange: (ThemeMode) -> Unit) {
    Row(
        Modifier
            .clip(RoadSignShape.Plate)
            .plateBorder(MaterialTheme.avelren.line)
    ) {
        listOf(ThemeMode.LIGHT to "Світла", ThemeMode.DARK to "Темна").forEach { (m, label) ->
            val active = mode == m
            Text(
                text = label.uppercase(),
                modifier = Modifier
                    .clickable { onChange(m) }
                    .background(if (active) MaterialTheme.avelren.go else Color.Transparent)
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                color = if (active) MaterialTheme.avelren.onGo else MaterialTheme.avelren.ink,
                fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.labelLarge,
            )
        }
    }
}
