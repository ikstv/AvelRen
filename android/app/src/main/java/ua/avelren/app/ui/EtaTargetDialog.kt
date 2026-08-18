package ua.avelren.app.ui

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SelectableDates
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
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

private val KYIV_ZONE: ZoneId = ZoneId.of("Europe/Kyiv")

/**
 * Choosing the target entry time: first the date, then the hour.
 *
 * The date is mandatory, not just the time of day: queues here last for days, and
 * "22:15" without a date would mean different moments for Yahodyn with its week of
 * waiting and for an empty Porubne.
 *
 * Past dates are unavailable — the server would reject a target in the past
 * anyway, but it is better to prevent the mistake than to show an error after.
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
        Step.DATE -> AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("Коли хочете в'їхати?") },
            text = { DatePicker(state = dateState, colors = DatePickerDefaults.colors()) },
            confirmButton = {
                TextButton(
                    enabled = dateState.selectedDateMillis != null,
                    onClick = { step = Step.TIME },
                ) { Text("Далі") }
            },
            dismissButton = { TextButton(onClick = onDismiss) { Text("Скасувати") } },
        )

        Step.TIME -> AlertDialog(
            onDismissRequest = onDismiss,
            title = { Text("О котрій?") },
            text = { TimePicker(state = timeState) },
            confirmButton = {
                TextButton(onClick = {
                    val millis = dateState.selectedDateMillis ?: return@TextButton
                    val date = Instant.ofEpochMilli(millis).atZone(ZoneOffset.UTC).toLocalDate()
                    // The user thinks in Kyiv time, the server — in UTC.
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
