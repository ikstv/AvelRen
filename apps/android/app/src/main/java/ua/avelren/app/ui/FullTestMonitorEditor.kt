package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.heightIn
import androidx.compose.ui.Modifier
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import ua.avelren.app.data.EditableMonitor
import ua.avelren.app.data.MonitorValue

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun FullTestMonitorEditor(
    original: EditableMonitor,
    title: String,
    onSave: (MonitorValue) -> Unit,
    onDismiss: () -> Unit,
    busy: Boolean,
    error: String?,
    now: Instant = Instant.now(),
) {
    val zone = remember { ZoneId.of("Europe/Kyiv") }
    val initial = remember(original) { original.targetAt?.let { runCatching { Instant.parse(it).atZone(zone) }.getOrNull() } }
    val today = now.atZone(zone).toLocalDate()
    val days = remember(today, initial) {
        ((0L..4L).map { today.plusDays(it) } + listOfNotNull(initial?.takeIf { it.toInstant().isAfter(now) }?.toLocalDate())).distinct().sorted()
    }
    var threshold by remember(original) { mutableIntStateOf(original.threshold ?: 100) }
    var day by remember(original) { mutableStateOf(initial?.toLocalDate()?.takeIf { it in days } ?: today) }
    var hour by remember(original) { mutableIntStateOf(initial?.hour ?: now.atZone(zone).plusHours(1).hour) }
    var editedTime by remember(original) { mutableStateOf(false) }
    val selectedInstant = if (!editedTime && initial != null) initial.toInstant() else day.atTime(hour, 0).atZone(zone).toInstant()
    var timeExpired by remember(original) { mutableStateOf(false) }
    val valid = original.threshold != null || selectedInstant.isAfter(now)
    val dismiss = { if (!busy) onDismiss() }
    FullTestDialog(
        title = title,
        onDismiss = dismiss,
        actions = {
            FullTestDialogAction(if (busy) "Збереження…" else "Зберегти", {
                if (original.threshold != null) onSave(MonitorValue.Threshold(threshold))
                else if (selectedInstant.isAfter(Instant.now())) onSave(MonitorValue.Eta(selectedInstant.toString()))
                else timeExpired = true
            }, primary = true, enabled = !busy && valid)
            FullTestDialogAction("Скасувати", dismiss, enabled = !busy)
        },
    ) {
        if (original.threshold != null) {
            Text("Поріг авто")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                (50..400 step 50).forEach { value ->
                    FilterChip(modifier = Modifier.heightIn(min = 48.dp), selected = threshold == value, onClick = { threshold = value }, enabled = !busy, label = { Text("$value") })
                }
            }
        } else {
            Text("Бажаний час в’їзду · Київ")
            initial?.let { Text("Поточний: ${it.format(DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm"))}") }
            Text("День")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                days.forEach { date ->
                    FilterChip(modifier = Modifier.heightIn(min = 48.dp), selected = day == date, onClick = { day = date; editedTime = true; timeExpired = false }, enabled = !busy,
                        label = { Text(date.format(DateTimeFormatter.ofPattern("dd.MM"))) })
                }
            }
            Text("Година")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                (0..23).forEach { value ->
                    FilterChip(modifier = Modifier.heightIn(min = 48.dp), selected = hour == value, onClick = { hour = value; editedTime = true; timeExpired = false }, enabled = !busy,
                        label = { Text("%02d:00".format(value)) })
                }
            }
            if (!valid || timeExpired) Text("Оберіть майбутній час.", color = MaterialTheme.colorScheme.error)
        }
        if (busy) Text("Перевіряємо та зберігаємо зміни…")
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}

