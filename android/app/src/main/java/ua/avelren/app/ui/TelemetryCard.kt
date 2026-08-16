package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Card
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.BuildConfig
import ua.avelren.app.data.Api
import ua.avelren.app.ui.theme.avelren
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
    // PR-B: якщо backend дав реальні поля — рахуємо на них; інакше fallback
    // на непрямі сигнали.
    val upstreamStatus = if (t.last_collector_run != null) {
        ServerDashboardStatus.upstream(
            t.last_collector_run, t.last_collector_success, t.problems, nowEpochSeconds
        )
    } else {
        ServerDashboardStatus.upstream(t.problems)
    }
    val servicesOverall = if (t.services.isNotEmpty()) {
        ServerDashboardStatus.overall(t.services.map { ServerDashboardStatus.service(it) })
    } else SectionStatus.UNKNOWN
    val inodesStatus = ServerDashboardStatus.inodes(t.inodes)
    val billingStatus = ServerDashboardStatus.billing()

    val overall = ServerDashboardStatus.overall(
        listOf(hostStatus, servicesOverall, collectorStatus, databaseStatus,
            backupStatus, certStatus, watchdogStatus, upstreamStatus, inodesStatus)
    )

    Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("СЕРВЕР", style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.avelren.ink)

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
            HostSection(t.system, t.inodes, inodesStatus)

            SectionHeader("🐳 Services", servicesOverall)
            ServicesSection(t.services, t.pipeline)

            SectionHeader("📡 Collector", collectorStatus)
            CollectorSection(t.pipeline, t.last_collector_run, t.last_collector_success,
                nowEpochSeconds)

            SectionHeader("🌐 ЄЧерга", upstreamStatus)
            UpstreamSection(t.upstream, t.last_collector_run, t.last_collector_success,
                t.problems)

            SectionHeader("🗄 Database", databaseStatus)
            DatabaseSection(t.pipeline)

            SectionHeader("🔔 Notifications", SectionStatus.UNKNOWN)
            NotificationsSection(t.pipeline)

            SectionHeader("👁 Watchdog", watchdogStatus)
            WatchdogSection(t.problems)

            SectionHeader("💾 Backup", backupStatus)
            BackupSection(t.backups)

            SectionHeader("🔒 Certificate", certStatus)
            CertificateSection(t.certificate)

            SectionHeader("💰 Витрати", billingStatus)
            BillingSection()

            SectionHeader("📦 Version", SectionStatus.UNKNOWN)
            VersionSection(t.version, t.docker)
        }
    }
}

@Composable
private fun SectionHeader(title: String, status: SectionStatus) {
    HorizontalDivider(color = MaterialTheme.avelren.line, modifier = Modifier.padding(vertical = 8.dp))
    Row(
        modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.avelren.ink)
        StatusDot(status)
    }
}

/**
 * Сигнальна крапка замість emoji-статусу (🟢/🟡/🔴/⚪) — та сама семантика
 * ROAD SIGN, що й скрізь у застосунку: зелений/жовтий/червоний/нейтральний.
 * `SectionStatus` лишається чистою логікою без Compose (юніт-тести без
 * інструментації) — мапінг на колір живе тут, у точці рендеру.
 */
@Composable
private fun StatusDot(status: SectionStatus) {
    val avelren = MaterialTheme.avelren
    val color = when (status) {
        SectionStatus.OK -> avelren.go
        SectionStatus.WARN -> avelren.warn
        SectionStatus.ERROR -> avelren.closed
        SectionStatus.UNKNOWN -> avelren.ink2
    }
    Box(Modifier.size(10.dp).clip(CircleShape).background(color))
}

@Composable
private fun HostSection(
    system: Api.TelemetrySystem,
    inodes: Api.TelemetryInodes?,
    inodesStatus: SectionStatus,
) {
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

    // Inode usage. Заповнена filesystem за inode виглядає як «диску купа»,
    // поки не спробуєш створити файл — тому окрема лінія.
    val inodesText = when {
        inodes?.used_percent == null -> "⚪ невідомо"
        inodes.total != null -> "${inodes.used_percent}% (${inodes.used}/${inodes.total})"
        else -> "${inodes.used_percent}%"
    }
    Line("Inode ${inodesStatus.emoji}", inodesText)
}

@Composable
private fun ServicesSection(
    services: List<Api.TelemetryService>,
    pipeline: Api.TelemetryPipeline,
) {
    if (services.isEmpty()) {
        // Backend без PR-B — fallback на непрямі сигнали (як у PR-A).
        Line("api", ServerDashboardStatus.apiService().emoji + " OK (непрямо)")
        Line("db", ServerDashboardStatus.dbService(pipeline).emoji +
            if (pipeline.observations > 0) " OK (непрямо)" else " невідомо")
        Line("collector/notifier/watchdog/caddy", "⚪ backend без PR-B")
        return
    }
    services.forEach { svc ->
        val st = ServerDashboardStatus.service(svc)
        val details = buildString {
            append(svc.status ?: "?")
            svc.health?.let { append(" · $it") }
            svc.restart_count?.let { rc -> if (rc > 0) append(" · restart ×$rc") }
            if (svc.oom_killed == true) append(" · OOM")
            svc.exit_code?.let { append(" · exit $it") }
        }
        Line("${st.emoji} ${svc.name}", details)
    }
}

@Composable
private fun CollectorSection(
    pipeline: Api.TelemetryPipeline,
    lastRun: Api.TelemetryLastRun?,
    lastSuccess: Api.TelemetryLastSuccess?,
    nowEpochSeconds: Long,
) {
    val age = ServerDashboardStatus.observationAgeSeconds(
        pipeline.last_observation, nowEpochSeconds)
    Line("Свіжість даних", age?.let { formatAgeSeconds(it) } ?: "⚪ невідомо")
    Line("Останнє спостереження", pipeline.last_observation ?: "⚪ невідомо")
    Line("Успішних циклів / год",
        pipeline.runs_last_hour?.toString() ?: "⚪ невідомо")
    Line("Помилок за годину", "${pipeline.errors_last_hour}")
    Line("Повнота", "${pipeline.completeness_percent}%")

    // PR-B: реальний останній цикл — з HTTP-статусом і причиною помилки.
    if (lastRun != null) {
        val runText = buildString {
            lastRun.http_status?.let { append("HTTP $it") } ?: append("HTTP ?")
            lastRun.duration_ms?.let { append(" · $it мс") }
            lastRun.rows_written?.let { append(" · $it рядків") }
            lastRun.error?.let { append(" · ⚠ $it") }
        }
        Line("Останній цикл", runText)
        Line("Час циклу", lastRun.time ?: "⚪ невідомо")
    }
    if (lastSuccess != null) {
        val successAge = ServerDashboardStatus.observationAgeSeconds(
            lastSuccess.time, nowEpochSeconds)
        Line("Останній успіх",
            successAge?.let { formatAgeSeconds(it) } ?: "⚪ невідомо")
    }
}

@Composable
private fun UpstreamSection(
    upstream: Api.TelemetryUpstream?,
    lastRun: Api.TelemetryLastRun?,
    lastSuccess: Api.TelemetryLastSuccess?,
    problems: List<Api.HealthProblem>,
) {
    if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
        Line("Стан", "🔴 недоступний (див. Watchdog)")
    }
    Line("Ендпоінт", upstream?.workload_url ?: "⚪ невідомо")
    Line("Тип ТЗ", upstream?.vehicle_type?.toString() ?: "⚪ невідомо")
    Line("Інтервал",
        upstream?.poll_interval_seconds?.let { "$it с" } ?: "⚪ невідомо")
    Line("HTTP статус (останній цикл)",
        lastRun?.http_status?.toString() ?: "⚪ невідомо")
    Line("Помилка останнього циклу", lastRun?.error ?: "—")
    Line("Останній успішний запит", lastSuccess?.time ?: "⚪ невідомо")
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
private fun BackupSection(backups: Api.TelemetryBackups) {
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
private fun VersionSection(version: Api.TelemetryVersion?, docker: Api.TelemetryDocker?) {
    Line("Застосунок", "v${BuildConfig.VERSION_NAME} (code ${BuildConfig.VERSION_CODE})")
    Line("Server app version", version?.app_version ?: "⚪ невідомо")
    Line("Server commit",
        version?.git_sha?.let { it.take(12) } ?: "⚪ невідомо")
    Line("Migrations", version?.migrations_version ?: "⚪ невідомо")
    Line("Docker daemon", docker?.daemon_version ?: "⚪ невідомо")
    Line("Docker Compose", docker?.compose_version ?: "⚪ невідомо")
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
