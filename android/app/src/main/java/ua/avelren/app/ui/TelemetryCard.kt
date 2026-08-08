package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.Api

/**
 * Телеметрія сервера. Показується лише на адміністративному пристрої —
 * звичайному користувачеві внутрішній устрій не потрібен.
 */
@Composable
fun TelemetryCard(t: Api.Telemetry?) {
    if (t == null) return

    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Сервер", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold)

            // Проблеми — найперше, заради чого цей екран узагалі відкривають.
            if (t.problems.isNotEmpty()) {
                t.problems.forEach {
                    Text("⚠ ${it.detail ?: it.kind}",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(top = 6.dp))
                }
                HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
            } else {
                Text("Проблем немає", style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(bottom = 6.dp))
            }

            Line("Час роботи", formatUptime(t.system.uptime_seconds))
            Line("Навантаження", "${t.system.load_1m} на ${t.system.cpu_count} ядра")
            Line("Пам'ять", "${t.system.memory_used_mb} / ${t.system.memory_total_mb} МБ")
            Line("Swap", "${t.system.swap_used_mb} / ${t.system.swap_total_mb} МБ")
            Line("Диск", "${t.system.disk_free_gb} ГБ вільно з ${t.system.disk_total_gb}")
            t.system.disk_used_percent?.let {
                LinearProgressIndicator(
                    progress = { it / 100f },
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                )
            }
            Line("Трафік", "↓ ${t.network.rx_total_gb} ГБ  ↑ ${t.network.tx_total_gb} ГБ")

            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
            Text("Збір даних", fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.bodyMedium)

            Line("Спостережень", "${t.pipeline.observations}")
            Line("Пунктів активних", "${t.pipeline.checkpoints_active}")
            // Повнота нижче 100% означає прогалини в історії, а їх не відновиш.
            Line("Повнота за годину", "${t.pipeline.completeness_percent}%")
            Line("Помилок за годину", "${t.pipeline.errors_last_hour}")
            Line("База", "${t.pipeline.db_size_mb} МБ")
            Line("Пристроїв", "${t.pipeline.devices}")
            Line("Підписок", "${t.pipeline.subscriptions + t.pipeline.eta_targets}")
            Line("Пушів надіслано", "${t.pipeline.pushes_sent}")

            HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))

            t.certificate.days_left?.let { Line("Сертифікат", "$it днів") }
            t.backups.age_hours?.let {
                Line("Остання копія", if (it < 1) "щойно" else "$it год тому")
            } ?: Line("Остання копія", "немає")
            // Оновлення пакетів. Показуємо завжди — «немає» теж інформація:
            // порожній рядок не відрізниш від «дані не дійшли». Security
            // виносимо окремо: саме вони визначають терміновість.
            Line(
                "Оновлення",
                when {
                    t.system.updates_pending == 0 -> "немає"
                    t.system.updates_security > 0 ->
                        "${t.system.updates_pending} (${t.system.updates_security} безпекових)"
                    else -> "${t.system.updates_pending}"
                },
            )
            if (t.system.reboot_required) {
                Line("Перезавантаження", "потрібне ${t.system.reboot_pending_days ?: 0} дн.")
            }
        }
    }
}

@Composable
private fun Line(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall)
        Text(value, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Bold)
    }
}

private fun formatUptime(seconds: Int?): String {
    if (seconds == null) return "—"
    val d = seconds / 86400
    val h = (seconds % 86400) / 3600
    return if (d > 0) "$d д $h год" else "$h год"
}
