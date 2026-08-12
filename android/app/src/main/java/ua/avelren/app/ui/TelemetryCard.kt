package ua.avelren.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import ua.avelren.app.BuildConfig
import ua.avelren.app.data.Api
import java.time.Instant

/**
 * Server Dashboard для адмін-пристрою. Показує все, що вже віддає
 * `/admin/telemetry`, у секційній структурі. Ніколи не вигадує значення:
 * якщо поле відсутнє — рендериться ⚪ Unknown, а не 🟢 OK. Це основний
 * інваріант — тихий провал моніторингу гірший за відсутність моніторингу.
 *
 * Розширення сервером (per-container статуси, upstream ЄЧерга, версії, білінг)
 * приходять з PR-B (backend telemetry) та PR-C (Hetzner billing). До того
 * відповідні секції показують чесний ⚪ Unknown із поясненням.
 */
@Composable
fun TelemetryCard(t: Api.Telemetry?) {
    if (t == null) return

    // "Now" береться один раз на композицію: усе всередині одного recompose
    // порівнюється з тим самим часом (детерміністично).
    val nowEpochSeconds = System.currentTimeMillis() / 1000L

    val hostStatus = ServerDashboardStatus.host(t.system)
    val collectorStatus = ServerDashboardStatus.collector(t.pipeline, t.problems, nowEpochSeconds)
    val databaseStatus = ServerDashboardStatus.database(t.pipeline)
    val backupStatus = ServerDashboardStatus.backup(t.backups)
    val certStatus = ServerDashboardStatus.certificate(t.certificate)
    val watchdogStatus = ServerDashboardStatus.watchdog(t.problems)
    val upstreamStatus = ServerDashboardStatus.upstream(t.problems)
    val billingStatus = ServerDashboardStatus.billing()

    val overall = ServerDashboardStatus.overall(
        listOf(hostStatus, collectorStatus, databaseStatus, backupStatus,
            certStatus, watchdogStatus)
    )

    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Сервер", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold)

            SectionHeader("Загальний статус", overall)
            if (t.problems.isNotEmpty()) {
                t.problems.forEach {
                    Text("⚠ ${it.detail ?: it.kind}",
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 2.dp))
                }
            } else {
                Line("Проблеми", "немає")
            }

            SectionHeader("🖥 Host", hostStatus)
            HostSection(t.system, nowEpochSeconds)

            SectionHeader("🐳 Services", SectionStatus.UNKNOWN)
            ServicesSection(t.pipeline)

            SectionHeader("📡 Collector", collectorStatus)
            CollectorSection(t.pipeline, nowEpochSeconds)

            SectionHeader("🌐 ЄЧерга", upstreamStatus)
            UpstreamSection(t.problems)

            SectionHeader("🗄 Database", databaseStatus)
            DatabaseSection(t.pipeline)

            SectionHeader("🔔 Notifications", SectionStatus.UNKNOWN)
            NotificationsSection(t.pipeline)

            SectionHeader("👁 Watchdog", watchdogStatus)
            WatchdogSection(t.problems)

            SectionHeader("💾 Backup", backupStatus)
            BackupSection(t.backups, nowEpochSeconds)

            SectionHeader("🔒 Certificate", certStatus)
            CertificateSection(t.certificate)

            SectionHeader("💰 Витрати", billingStatus)
            BillingSection()

            SectionHeader("📦 Version", SectionStatus.UNKNOWN)
            VersionSection()
        }
    }
}

@Composable
private fun SectionHeader(title: String, status: SectionStatus) {
    HorizontalDivider(modifier = Modifier.padding(vertical = 8.dp))
    Row(
        modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(title, fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodyMedium)
        Text(status.emoji, style = MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun HostSection(system: Api.TelemetrySystem, nowEpochSeconds: Long) {
    if (system.stale == true) {
        Text("⚠ Host-снапшот протух — дані нижче застаріли",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(bottom = 4.dp))
    }

    Line("Час роботи", formatUptime(system.uptime_seconds))

    val load1 = system.load_1m
    val load5 = system.load_5m
    val cpu = system.cpu_count
    val loadValue = when {
        load1 == null || cpu == null -> "⚪ невідомо"
        load5 != null -> "$load1 / $load5 на $cpu ядра"
        else -> "$load1 на $cpu ядра"
    }
    Line("Навантаження", loadValue)

    val memText = if (system.memory_total_mb > 0) {
        val pct = ServerDashboardStatus.memoryPercent(system)
        "${system.memory_used_mb} / ${system.memory_total_mb} МБ" +
            (if (pct != null) " ($pct%)" else "")
    } else "⚪ невідомо"
    Line("Пам'ять", memText)

    if (system.swap_total_mb > 0) {
        Line("Swap", "${system.swap_used_mb} / ${system.swap_total_mb} МБ")
    }

    if (system.disk_total_gb > 0) {
        Line("Диск", "${system.disk_free_gb} ГБ вільно з ${system.disk_total_gb}")
        system.disk_used_percent?.let {
            LinearProgressIndicator(
                progress = { it / 100f },
                modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
            )
        }
    } else Line("Диск", "⚪ невідомо")

    Line("Оновлення", formatUpdates(system.updates_pending, system.updates_security))
    if (system.reboot_required) {
        Line("Перезавантаження", "потрібне ${system.reboot_pending_days ?: 0} дн.")
    }

    val snapAge = system.snapshot_age_seconds
    Line("Свіжість host-снапшоту",
        snapAge?.let { formatAgeSeconds(it.toLong()) } ?: "⚪ невідомо")
}

@Composable
private fun ServicesSection(pipeline: Api.TelemetryPipeline) {
    // Per-container статуси приходять з PR-B. Зараз доступні лише два непрямі
    // сигнали: api (сам факт відповіді), db (запит до pipeline повернувся).
    // Решта — чесний ⚪ Unknown, а не «⚠ здається живий».
    Line("api", ServerDashboardStatus.apiService().emoji + " OK")
    Line("db", ServerDashboardStatus.dbService(pipeline).emoji +
        if (pipeline.observations > 0) " OK" else " невідомо")
    Line("collector", "⚪ per-container статус — PR-B")
    Line("notifier", "⚪ per-container статус — PR-B")
    Line("watchdog", "⚪ per-container статус — PR-B")
    Line("caddy", "⚪ per-container статус — PR-B")
}

@Composable
private fun CollectorSection(pipeline: Api.TelemetryPipeline, nowEpochSeconds: Long) {
    val age = ServerDashboardStatus.observationAgeSeconds(
        pipeline.last_observation, nowEpochSeconds)
    Line("Свіжість даних", age?.let { formatAgeSeconds(it) } ?: "⚪ невідомо")
    Line("Останнє спостереження", pipeline.last_observation ?: "⚪ невідомо")
    Line("Успішних циклів / год",
        pipeline.runs_last_hour?.toString() ?: "⚪ невідомо")
    Line("Помилок за годину", "${pipeline.errors_last_hour}")
    Line("Повнота", "${pipeline.completeness_percent}%")
}

@Composable
private fun UpstreamSection(problems: List<Api.HealthProblem>) {
    // Upstream-специфічну телеметрію (HTTP статус, URL v5) додає PR-B у
    // /admin/telemetry. До того — чесно unknown + непрямий сигнал через
    // collector_silent, який уже видно в Watchdog.
    if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
        Line("Стан", "🔴 недоступний (див. Watchdog)")
    } else {
        Line("Стан", "⚪ окрема телеметрія — PR-B")
    }
    Line("Ендпоінт", "⚪ буде у PR-B")
    Line("Останній успішний запит", "⚪ буде у PR-B")
}

@Composable
private fun DatabaseSection(pipeline: Api.TelemetryPipeline) {
    Line("Розмір", "${pipeline.db_size_mb} МБ")
    Line("Спостережень", "${pipeline.observations}")
    Line("Пунктів активних", "${pipeline.checkpoints_active}")
    Line("Активних пристроїв", "${pipeline.devices}")
    Line("Збираємо з",
        pipeline.collecting_since ?: "⚪ невідомо")
}

@Composable
private fun NotificationsSection(pipeline: Api.TelemetryPipeline) {
    Line("Пушів надіслано (всього)", "${pipeline.pushes_sent}")
    Line("Підписок активних", "${pipeline.subscriptions}")
    Line("ETA-цілей активних", "${pipeline.eta_targets}")
    Line("Активних алертів",
        pipeline.alerts_pending?.toString() ?: "⚪ невідомо")
    Line("Notifier heartbeat", "⚪ буде у PR-B")
}

@Composable
private fun WatchdogSection(problems: List<Api.HealthProblem>) {
    if (problems.isEmpty()) {
        Line("Активних тривог", "0")
    } else {
        Line("Активних тривог", "${problems.size}")
        problems.forEach { p ->
            Line("• ${p.kind}", p.detail ?: "")
        }
    }
}

@Composable
private fun BackupSection(backups: Api.TelemetryBackups, nowEpochSeconds: Long) {
    val ageText = when {
        backups.age_hours == null -> "⚪ немає"
        backups.age_hours < 1 -> "щойно"
        else -> "${backups.age_hours} год тому"
    }
    Line("Остання копія", ageText)
    if (backups.stale) Line("Статус", "🔴 протухла")
    backups.last_run?.let {
        Line("Час останнього запуску (unix)", "$it")
    }
    Line("Remote verification", "⚪ буде у PR-B")
}

@Composable
private fun CertificateSection(cert: Api.TelemetryCert) {
    Line("Днів до кінця", cert.days_left?.toString() ?: "⚪ невідомо")
    cert.issuer?.let { Line("Видавець", it) }
    cert.error?.let { Line("Помилка", "🔴 $it") }
}

@Composable
private fun BillingSection() {
    // Джерело білінгу з'явиться в PR-C (Hetzner Cloud API, read-only token).
    // До того чесно показуємо ⚪ Unknown із зазначенням причини. Розраховані
    // значення (uptime × ціна) НЕ показуємо як «витрачено» — це естімейт, і
    // називати його фактичним списанням = вводити в оману.
    Line("Стан", "⚪ Unknown — billing source не налаштований")
    Line("Джерело", "буде: Hetzner Cloud (PR-C)")
}

@Composable
private fun VersionSection() {
    Line("Застосунок", "v${BuildConfig.VERSION_NAME} (code ${BuildConfig.VERSION_CODE})")
    Line("Server app version", "⚪ буде у PR-B")
    Line("Server commit", "⚪ буде у PR-B")
    Line("Migrations", "⚪ буде у PR-B")
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
    if (seconds == null) return "⚪ невідомо"
    val d = seconds / 86400
    val h = (seconds % 86400) / 3600
    return if (d > 0) "$d д $h год" else "$h год"
}

private fun formatUpdates(pending: Int?, security: Int?): String {
    val sec = security ?: 0
    return when {
        pending == null -> "невідомо"
        pending == 0 -> "немає"
        sec > 0 -> "$pending ($sec безпекових)"
        else -> "$pending"
    }
}

private fun formatAgeSeconds(seconds: Long): String {
    if (seconds < 0) return "невідомо"
    val m = seconds / 60
    val h = m / 60
    val d = h / 24
    return when {
        d > 0 -> "$d д ${h % 24} год тому"
        h > 0 -> "$h год ${m % 60} хв тому"
        m > 0 -> "$m хв тому"
        else -> "щойно"
    }
}
