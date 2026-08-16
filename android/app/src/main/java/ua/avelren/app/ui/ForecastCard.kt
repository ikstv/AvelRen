package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.Api
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.plateBorder
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val DAY_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM")
private val HOUR_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")

/**
 * Функція №3: АІ Прогноз.
 *
 * Поки історії замало, картка показує саме це, а не вигадані числа: прогноз
 * на добі даних виглядав би переконливо й був би брехнею, а на ньому люди
 * планують рейси.
 */
@Composable
fun ForecastCard(forecast: Api.Forecast?) {
    if (forecast == null) return

    Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("АІ ПРОГНОЗ", style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.avelren.ink)

            when (forecast.status) {
                "collecting" -> Collecting(forecast)
                else -> Points(forecast)
            }
        }
    }
}

@Composable
private fun Collecting(f: Api.Forecast) {
    val progress = (f.weeks_collected / f.weeks_needed).coerceIn(0.0, 1.0).toFloat()

    val percent = (progress * 100).toInt()

    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text("Навчання на цьому пункті", style = MaterialTheme.typography.bodyMedium)
        Text("$percent%", style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Bold)
    }
    LinearProgressIndicator(
        progress = { progress },
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
    )
    Text(
        "${f.weeks_collected} з ${f.weeks_needed} тижнів історії",
        style = MaterialTheme.typography.bodySmall,
    )
    f.ready_at?.let {
        Text(
            "Прогноз запрацює приблизно ${formatDay(it)}",
            style = MaterialTheme.typography.bodySmall,
        )
    }
    Text(
        "Раніше не показую: на такій кількості даних прогноз був би вигадкою.",
        style = MaterialTheme.typography.bodySmall,
        modifier = Modifier.padding(top = 6.dp),
    )
}

@Composable
private fun Points(f: Api.Forecast) {
    if (f.status == "preliminary") {
        Text(
            "Попередній: даних ${f.weeks_collected} з ${f.weeks_needed} тижнів",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(top = 2.dp),
        )
    }

    if (f.points.isEmpty()) {
        Text("Даних для цих годин ще немає", style = MaterialTheme.typography.bodySmall)
        return
    }

    // Показуємо кожну шосту точку: 24 рядки поспіль ніхто не читає.
    f.points.filterIndexed { i, _ -> i % 6 == 0 }.take(4).forEach { p ->
        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(formatHour(p.time), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.avelren.ink2)
            // Діапазон, а не одне число: «2-4 дні» чесніше за «3 дні 14 годин».
            Text(
                "${humanize(p.wait_seconds_low)} – ${humanize(p.wait_seconds_high)}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.avelren.ink,
                modifier = Modifier
                    .plateBorder(MaterialTheme.avelren.line)
                    .padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
    }
}

private fun humanize(seconds: Int): String {
    val h = seconds / 3600
    return when {
        h >= 24 -> "${h / 24} д ${h % 24} год"
        h > 0 -> "$h год"
        else -> "${seconds / 60} хв"
    }
}

private fun formatHour(iso: String): String =
    runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(HOUR_FMT) }
        .getOrDefault(iso)

private fun formatDay(iso: String): String =
    runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(DAY_FMT) }
        .getOrDefault(iso)
