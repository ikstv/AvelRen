package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.Api
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val KYIV_TZ: ZoneId = ZoneId.of("Europe/Kyiv")
private val TARGET_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

/**
 * Active subscriptions with the ability to cancel.
 *
 * Without this screen, a mistaken tap on "50" instead of "500" would mean
 * notifications forever — and they are deliberately non-swipeable. Creating
 * something that cannot be turned off is worse than creating nothing.
 */
@Composable
fun SubscriptionsSection(
    subscriptions: List<Api.Subscription>,
    targets: List<Api.EtaTarget>,
    onRemoveSubscription: (Long) -> Unit,
    onRemoveTarget: (Long) -> Unit,
    enabled: Boolean = true,
) {
    if (subscriptions.isEmpty() && targets.isEmpty()) return

    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Що я відстежую", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold)

            subscriptions.forEach { s ->
                RemovableRow(
                    text = "${s.flag_emoji ?: ""} ${s.title}",
                    detail = "поріг ${s.threshold} авто",
                    enabled = enabled,
                    onRemove = { onRemoveSubscription(s.id) },
                )
            }

            targets.forEach { t ->
                RemovableRow(
                    text = "${t.flag_emoji ?: ""} ${t.title}",
                    detail = "в'їзд ${formatTarget(t.target_at)}",
                    enabled = enabled,
                    onRemove = { onRemoveTarget(t.id) },
                )
            }
        }
    }
}

@Composable
private fun RemovableRow(text: String, detail: String, enabled: Boolean, onRemove: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text, style = MaterialTheme.typography.bodyMedium)
            Text(detail, style = MaterialTheme.typography.bodySmall)
        }
        // Protected action: in a non-Ready state delete is disabled (B4).
        TextButton(onClick = onRemove, enabled = enabled) { Text("Прибрати") }
    }
}

private fun formatTarget(iso: String): String =
    runCatching {
        OffsetDateTime.parse(iso).atZoneSameInstant(KYIV_TZ).format(TARGET_FMT)
    }.getOrDefault(iso)
