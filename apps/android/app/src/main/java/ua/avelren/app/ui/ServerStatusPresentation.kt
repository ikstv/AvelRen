package ua.avelren.app.ui

import java.time.Instant
import java.time.Duration
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.ktor.client.plugins.ClientRequestException
import io.ktor.http.HttpStatusCode
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import ua.avelren.app.data.Api

internal data class ServerStatusPresentation(val percent: Double?, val measuredAt: String?)

internal fun serverStatusPresentation(status: Api.ServerCpuStatus?, now: Instant): ServerStatusPresentation {
    val measured = status?.measured_at?.let { runCatching { Instant.parse(it) }.getOrNull() }
    val age = measured?.let { Duration.between(it, now) }
    val cpu = status?.cpu_percent
    val fresh = status != null && !status.stale && status.sample_seconds == 1 &&
        age != null && !age.isNegative && age <= Duration.ofSeconds(300) &&
        cpu != null && cpu.isFinite() && cpu in 0.0..100.0
    val label = measured?.let {
        runCatching { DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm", Locale.ROOT)
            .withZone(ZoneId.of("Europe/Kyiv")).format(it) }.getOrNull()
    }
    return ServerStatusPresentation(if (fresh) cpu else null, label)
}

internal class ServerCpuLoader(private val fetch: suspend () -> Api.ServerCpuStatus) {
    var busy by mutableStateOf(false)
        private set
    var status by mutableStateOf<Api.ServerCpuStatus?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    suspend fun expireSnapshot(clock: () -> Instant = Instant::now) {
        val observed = status ?: return
        val now = clock()
        if (serverStatusPresentation(observed, now).percent == null) return
        val measured = Instant.parse(observed.measured_at!!)
        // Local one-shot expiry only; never fetches or retries. Cancellation is propagated.
        val waitMillis = Duration.between(now, measured.plusSeconds(300)).toMillis() + 1
        delay(waitMillis)
        if (status === observed) status = observed.copy(stale = true)
    }

    // Called on the screen's main coroutine context: set busy before first suspension.
    suspend fun refresh() {
        if (busy) return
        busy = true
        error = null
        try {
            coroutineScope {
                val visibleFeedback = launch { delay(400) }
                try {
                    status = fetch()
                } catch (cancelled: CancellationException) {
                    throw cancelled
                } catch (failure: Exception) {
                    status = status?.copy(stale = true)
                    error = if (failure is ClientRequestException && failure.response.status == HttpStatusCode.NotFound) {
                        "CPU ще недоступний на сервері."
                    } else {
                        "Не вдалося оновити дані. Перевірте з’єднання та спробуйте ще раз."
                    }
                }
                visibleFeedback.join()
            }
        } finally {
            busy = false
        }
    }
}
