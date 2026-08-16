package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TimePicker
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberTimePickerState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

private val KYIV_ZONE: ZoneId = ZoneId.of("Europe/Kyiv")

/**
 * Вибір цільового часу в'їзду: спершу дата, потім година.
 *
 * Дата обов'язкова, а не лише час доби: черги тут тривають днями, і «22:15»
 * без дати означало б різні моменти для Ягодина з його тижнем очікування
 * і для порожнього Порубного.
 *
 * Минулі дати недоступні — ціль у минулому сервер усе одно відхилить,
 * але краще не дати помилитись, ніж показати помилку після.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EtaTargetDialog(
    checkpointTitle: String,
    onDismiss: () -> Unit,
    onConfirm: (isoUtc: String, humanLocal: String) -> Unit,
) {
    var step by remember { mutableStateOf(Step.DATE) }

    val today = LocalDate.now(KYIV_ZONE)
    val dateState = rememberDatePickerState(
        initialSelectedDateMillis = today.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
        selectableDates = object : SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long): Boolean {
                val date = Instant.ofEpochMilli(utcTimeMillis).atZone(ZoneOffset.UTC).toLocalDate()
                return !date.isBefore(today)
            }
        },
    )
    val timeState = rememberTimePickerState(initialHour = 22, initialMinute = 15, is24Hour = true)

    when (step) {
        Step.DATE ->
            // ВАЖЛИВО: не AlertDialog. Стандартний AlertDialog обмежує ширину
            // платформним максимумом і додає власні горизонтальні відступи —
            // календарна сітка DatePicker (7 колонок) у цьому обмеженні не
            // вміщається, і колонка неділі та частина чисел обрізаються з
            // правого краю (виявлено вручну на пристрої, не вигадана проблема).
            // `usePlatformDefaultWidth = false` — задокументована Google
            // рекомендація саме для DatePicker у власному Dialog: вікно
            // підлаштовується під природну ширину вмісту, а не навпаки.
            Dialog(
                onDismissRequest = onDismiss,
                properties = DialogProperties(usePlatformDefaultWidth = false),
            ) {
                Surface(
                    shape = MaterialTheme.shapes.extraLarge,
                    tonalElevation = 6.dp,
                ) {
                    Column {
                        Text(
                            "Коли хочете в'їхати?",
                            style = MaterialTheme.typography.headlineMedium,
                            modifier = Modifier.padding(start = 24.dp, top = 24.dp, end = 24.dp),
                        )
                        DatePicker(state = dateState, colors = DatePickerDefaults.colors())
                        Row(
                            modifier = Modifier.fillMaxWidth().padding(end = 16.dp, bottom = 8.dp),
                            horizontalArrangement = Arrangement.End,
                        ) {
                            TextButton(onClick = onDismiss) { Text("Скасувати") }
                            TextButton(
                                enabled = dateState.selectedDateMillis != null,
                                onClick = { step = Step.TIME },
                            ) { Text("Далі") }
                        }
                    }
                }
            }

        Step.TIME -> AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("О котрій?") },
            text = { TimePicker(state = timeState) },
            confirmButton = {
                TextButton(onClick = {
                    val millis = dateState.selectedDateMillis ?: return@TextButton
                    val date = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                    // Користувач мислить київським часом, сервер — UTC.
                    val local = LocalDateTime.of(date, java.time.LocalTime.of(timeState.hour, timeState.minute))
                    val zoned = local.atZone(KYIV_ZONE)
                    onConfirm(
                        zoned.withZoneSameInstant(ZoneOffset.UTC)
                            .format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")),
                        zoned.format(DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")),
                    )
                }) { Text("Стежити") }
            },
            dismissButton = { TextButton(onClick = { step = Step.DATE }) { Text("Назад") } },
        )
    }
}

private enum class Step { DATE, TIME }
