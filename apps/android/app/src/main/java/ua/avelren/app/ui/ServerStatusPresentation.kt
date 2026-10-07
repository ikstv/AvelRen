package ua.avelren.app.ui

import java.time.Instant
import java.time.Duration
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
        runCatching { telemetryTimeLabel(it, now) }.getOrNull()
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
        val deadlines = mutableListOf<Instant>()
        if (serverStatusPresentation(observed, now).percent != null)
            deadlines += Instant.parse(observed.measured_at!!).plusSeconds(300)
        for ((resource, ttl, traffic) in listOf(
            Triple(observed.memory, 300L, false), Triple(observed.disk, 300L, false),
            Triple(observed.traffic, 7200L, true))) {
            if (resourceStatusPresentation(resource, now, ttl, traffic).percent != null)
                deadlines += Instant.parse(resource!!.measured_at!!).plusSeconds(ttl)
        }
        val deadline = deadlines.minOrNull() ?: return
        // One local expiry per nearest deadline; Compose restarts for remaining resources.
        val waitMillis = Duration.between(now, deadline).toMillis() + 1
        delay(waitMillis)
        if (status === observed) {
            val expiredAt = clock()
            fun expired(resource: Api.ServerResourceStatus?, ttl: Long, traffic: Boolean = false) =
                resource?.copy(stale = resourceStatusPresentation(resource, expiredAt, ttl, traffic).percent == null)
            status = observed.copy(stale = serverStatusPresentation(observed, expiredAt).percent == null,
                memory = expired(observed.memory, 300), disk = expired(observed.disk, 300),
                traffic = expired(observed.traffic, 7200, true))
        }
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
                    status = status?.let { it.copy(stale = true,
                        memory = it.memory?.copy(stale = true), disk = it.disk?.copy(stale = true),
                        traffic = it.traffic?.copy(stale = true)) }
                    error = if (failure is ClientRequestException && failure.response.status == HttpStatusCode.NotFound) {
                        "Телеметрія ще недоступна на сервері."
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
