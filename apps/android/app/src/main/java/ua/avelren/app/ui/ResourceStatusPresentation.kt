package ua.avelren.app.ui

import java.time.Instant
import java.time.Duration
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import ua.avelren.app.data.Api

internal data class ResourceStatusPresentation(val amountLabel: String?, val percent: Double?,
    val fillFraction: Float, val timeLabel: String?)

internal fun resourceStatusPresentation(status: Api.ServerResourceStatus?, now: Instant,
    maxAgeSeconds: Long, traffic: Boolean = false): ResourceStatusPresentation {
    val unavailable = ResourceStatusPresentation(null, null, 0f, null)
    val measured = status?.measured_at?.let { runCatching { Instant.parse(it) }.getOrNull() }
        ?: return unavailable
    val age = Duration.between(measured, now)
    val used = status.used_bytes ?: return unavailable
    val total = status.total_bytes ?: return unavailable
    if (status.stale || age.isNegative || age > Duration.ofSeconds(maxAgeSeconds) ||
        used < 0 || total <= 0 || (!traffic && used > total) ||
        (traffic && status.billing_month == null)) return unavailable
    val percent = used.toDouble() / total.toDouble() * 100.0
    val divisor = if (traffic) { if (total >= 1000000000000L) 1e12 else 1e9 } else 1073741824.0
    val unit = if (traffic) { if (total >= 1000000000000L) "ТБ" else "ГБ" } else "ГіБ"
    val amount = String.format(Locale.ROOT, "%.1f / %.1f %s", used / divisor, total / divisor, unit)
    val time = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm", Locale.ROOT)
        .withZone(ZoneId.of("Europe/Kyiv")).format(measured)
    return ResourceStatusPresentation(amount, percent, (percent / 100.0).coerceIn(0.0, 1.0).toFloat(), time)
}
