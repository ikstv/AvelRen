package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.avelren

@Composable
internal fun SurfaceForecastExplanation(receivedAt: Instant? = null, status: String? = null) {
    Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(16.dp), border = BorderStroke(1.dp, MaterialTheme.avelren.line)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Прогноз · BETA", color = AppAccent, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Text("Модель оцінює майбутню чергу за історією. Це орієнтир для планування; фактична черга й час в’їзду можуть змінитися.",
                color = AppInk, style = MaterialTheme.typography.bodyMedium)
            Text("Очікуване значення — центральна оцінка моделі. Діапазон показує можливий розкид, коли для нього є дані.",
                color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
            if (status == "preliminary") Text("Попередня оцінка: модель ще накопичує історію.",
                color = AppAccent, style = MaterialTheme.typography.bodySmall)
            receivedAt?.let {
                Text("Отримано: ${it.atZone(ZoneId.of("Europe/Kyiv")).format(DateTimeFormatter.ofPattern("dd.MM HH:mm:ss"))} · час за Києвом",
                    color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}
