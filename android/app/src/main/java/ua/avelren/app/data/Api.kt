package ua.avelren.app.data

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import ua.avelren.app.BuildConfig

/**
 * Клієнт нашого API.
 *
 * Тут немає і не може бути жодного звернення до echerha.gov.ua — застосунок
 * ходить виключно на власний сервер (див. AGENTS.md, правило 1).
 */
object Api {

    private val client = HttpClient(Android) {
        install(ContentNegotiation) {
            json(Json { ignoreUnknownKeys = true })
        }
    }

    private val base = BuildConfig.API_BASE_URL

    @Serializable
    data class Checkpoint(
        val id: Int,
        val title: String,
        val country_name: String? = null,
        val flag_emoji: String? = null,
    )

    @Serializable
    data class Workload(
        val checkpoint_id: Int,
        val title: String,
        val flag_emoji: String? = null,
        val vehicles_in_queue: Int,
        val wait_time_seconds: Int,
        val is_paused: Boolean,
        val entry_eta: String? = null,
    )

    @Serializable
    data class Subscription(
        val id: Long,
        val checkpoint_id: Int,
        val title: String,
        val flag_emoji: String? = null,
        val threshold: Int,
    )

    @Serializable
    data class TelemetrySystem(
        val uptime_seconds: Int? = null,
        val load_1m: Double? = null,
        val cpu_count: Int? = null,
        val memory_total_mb: Int = 0,
        val memory_used_mb: Int = 0,
        val swap_total_mb: Int = 0,
        val swap_used_mb: Int = 0,
        val disk_total_gb: Double = 0.0,
        val disk_free_gb: Double = 0.0,
        val disk_used_percent: Int? = null,
        val reboot_required: Boolean = false,
        val reboot_pending_days: Int? = null,
    )

    @Serializable
    data class TelemetryNetwork(val rx_total_gb: Double = 0.0, val tx_total_gb: Double = 0.0)

    @Serializable
    data class TelemetryPipeline(
        val observations: Long = 0,
        val checkpoints_active: Int = 0,
        val errors_last_hour: Int = 0,
        val devices: Int = 0,
        val subscriptions: Int = 0,
        val eta_targets: Int = 0,
        val pushes_sent: Long = 0,
        val db_size_mb: Double = 0.0,
        val completeness_percent: Int = 0,
    )

    @Serializable
    data class TelemetryCert(val days_left: Int? = null, val issuer: String? = null)

    @Serializable
    data class TelemetryBackups(val age_hours: Double? = null, val stale: Boolean = false)

    @Serializable
    data class HealthProblem(val kind: String, val detail: String? = null)

    @Serializable
    data class Telemetry(
        val system: TelemetrySystem,
        val network: TelemetryNetwork,
        val pipeline: TelemetryPipeline,
        val certificate: TelemetryCert,
        val backups: TelemetryBackups,
        val problems: List<HealthProblem> = emptyList(),
    )

    @Serializable
    data class EtaTarget(
        val id: Long,
        val checkpoint_id: Int,
        val title: String,
        val flag_emoji: String? = null,
        val target_at: String,
        val tolerance_seconds: Int,
        val is_active: Boolean,
    )

    @Serializable
    data class ForecastPoint(
        val time: String,
        val wait_seconds_low: Int,
        val wait_seconds_expected: Int,
        val wait_seconds_high: Int,
        val vehicles_expected: Int,
    )

    @Serializable
    data class Forecast(
        val checkpoint_id: Int,
        /** collecting — прогнозу немає; preliminary — попередній; ready — готовий. */
        val status: String,
        val weeks_collected: Double,
        val weeks_needed: Int,
        val ready_at: String? = null,
        val points: List<ForecastPoint> = emptyList(),
    )

    @Serializable
    private data class DeviceIn(val fcm_token: String, val platform: String = "android")

    @Serializable
    private data class DeviceOut(val device_id: String)

    @Serializable
    private data class TokenIn(val fcm_token: String)

    @Serializable
    private data class SubscriptionIn(val checkpoint_id: Int, val threshold: Int)

    @Serializable
    private data class EtaTargetIn(
        val checkpoint_id: Int,
        val target_at: String,
        val tolerance_seconds: Int = 900,
    )

    suspend fun registerDevice(fcmToken: String): String =
        client.post("$base/devices") {
            contentType(ContentType.Application.Json)
            setBody(DeviceIn(fcmToken))
        }.body<DeviceOut>().device_id

    suspend fun updateToken(deviceId: String, fcmToken: String) {
        client.put("$base/devices/token") {
            header("X-Device-Id", deviceId)
            contentType(ContentType.Application.Json)
            setBody(TokenIn(fcmToken))
        }
    }

    suspend fun checkpoints(): List<Checkpoint> = client.get("$base/checkpoints").body()

    suspend fun workload(): List<Workload> = client.get("$base/workload").body()

    /** Телеметрія доступна лише адмін-пристроям; для решти сервер віддає 403. */
    suspend fun telemetry(deviceId: String): Telemetry =
        client.get("$base/admin/telemetry") { header("X-Device-Id", deviceId) }.body()

    suspend fun forecast(checkpointId: Int, hours: Int = 24): Forecast =
        client.get("$base/forecast/$checkpointId?hours=$hours").body()

    suspend fun subscriptions(deviceId: String): List<Subscription> =
        client.get("$base/subscriptions") { header("X-Device-Id", deviceId) }.body()

    suspend fun subscribe(deviceId: String, checkpointId: Int, threshold: Int) {
        client.post("$base/subscriptions") {
            header("X-Device-Id", deviceId)
            contentType(ContentType.Application.Json)
            setBody(SubscriptionIn(checkpointId, threshold))
        }
    }

    suspend fun unsubscribe(deviceId: String, subscriptionId: Long) {
        client.delete("$base/subscriptions/$subscriptionId") {
            header("X-Device-Id", deviceId)
        }
    }

    suspend fun etaTargets(deviceId: String): List<EtaTarget> =
        client.get("$base/eta-targets") { header("X-Device-Id", deviceId) }.body()

    suspend fun deleteEtaTarget(deviceId: String, targetId: Long) {
        client.delete("$base/eta-targets/$targetId") { header("X-Device-Id", deviceId) }
    }

    suspend fun createEtaTarget(deviceId: String, checkpointId: Int, targetAtIso: String) {
        client.post("$base/eta-targets") {
            header("X-Device-Id", deviceId)
            contentType(ContentType.Application.Json)
            setBody(EtaTargetIn(checkpointId, targetAtIso))
        }
    }

    /** Кнопка «ОК». Після неї сервер припиняє повтори. */
    suspend fun ack(deviceId: String, alertId: Long, kind: String) {
        val path = if (kind == "eta") "eta-alerts" else "alerts"
        client.post("$base/$path/$alertId/ack") { header("X-Device-Id", deviceId) }
    }
}
