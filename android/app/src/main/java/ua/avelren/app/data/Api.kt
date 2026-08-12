package ua.avelren.app.data

import io.ktor.client.HttpClient
import io.ktor.client.HttpClientConfig
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.engine.HttpClientEngine
import io.ktor.client.plugins.ClientRequestException
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.put
import io.ktor.client.request.setBody
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.plugins.timeout
import io.ktor.http.ContentType
import io.ktor.http.HttpStatusCode
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import ua.avelren.app.BuildConfig

object Timeouts {
    const val CONNECT_MS = 10_000L
    const val SOCKET_MS = 15_000L
    const val REQUEST_MS = 20_000L
    const val ACK_REQUEST_MS = 5_000L
    const val ACK_RECEIVER_BUDGET_MS = 7_000L
}

/**
 * Клієнт нашого API.
 *
 * Тут немає і не може бути жодного звернення до echerha.gov.ua — застосунок
 * ходить виключно на власний сервер (див. AGENTS.md, правило 1).
 */
object Api {

    private val client = HttpClient(Android) { configure(Timeouts.REQUEST_MS) }

    internal fun clientFor(
        engine: HttpClientEngine,
        requestTimeoutMs: Long = Timeouts.REQUEST_MS,
    ): HttpClient = HttpClient(engine) { configure(requestTimeoutMs) }

    private fun HttpClientConfig<*>.configure(requestTimeoutMs: Long) {
        install(HttpTimeout) {
            connectTimeoutMillis = Timeouts.CONNECT_MS
            socketTimeoutMillis = Timeouts.SOCKET_MS
            requestTimeoutMillis = requestTimeoutMs
        }
        install(ContentNegotiation) {
            json(Json { ignoreUnknownKeys = true })
        }
        // Без цього Ktor 3 повертає non-2xx як «успіх» — виклики без body<>()
        // (updateToken, ack, delete) не помітили б 401 взагалі, і клієнт
        // після DB restore потрапляв у вічний loop 401 без re-registration
        // (NEW-AUTH-2). Тепер будь-який 4xx кидає ClientRequestException,
        // 5xx — ServerResponseException.
        expectSuccess = true
    }

    private val base = BuildConfig.API_BASE_URL

    /**
     * Розпізнає 401 будь-де в API-виклику. `AvelRenApp` та
     * `AvelRenMessagingService` використовують це, щоб очистити збережені
     * credentials і зареєструватися заново — типовий сценарій DB restore.
     * Ktor кидає `ClientRequestException` і на 4xx з body-decode, і на 4xx
     * без body — це одна точка обробки.
     */
    fun isStaleInstallation(exc: Throwable): Boolean =
        exc is ClientRequestException && exc.response.status == HttpStatusCode.Unauthorized

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
        // Час фактичного заміру (server observation time). Nullable — щоб старі
        // fixture/JSON без поля лишалися сумісними. Свіжість рахуємо саме з нього,
        // а не з часу HTTP-запиту (AND-4).
        val time: String? = null,
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
        // load_5m приходить з host-snapshot (PR-A). Nullable — старий сервер без
        // поля продовжує парситись.
        val load_5m: Double? = null,
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
        // Доступні оновлення пакетів. null (default) = перевірити не вдалося
        // або старий сервер без поля; 0 = перевірено, оновлень немає. Розрізняти
        // важливо: 0 приховав би збій probe за виглядом здорового хоста.
        val updates_pending: Int? = null,
        val updates_security: Int? = null,
        // Свіжість host-snapshot: null у старого сервера, число — вік у секундах.
        val snapshot_age_seconds: Int? = null,
        // Сервер сам виставляє true, якщо snapshot > 5 хв або зник. При true у
        // problems уже додано telemetry_snapshot_stale — тут дублюємо як явний
        // булевий сигнал для секції Host.
        val stale: Boolean? = null,
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
        // Час останнього спостереження (ISO-8601 з сервера). Джерело істини
        // «свіжості» конвеєра — з нього рахуємо age на клієнті. Nullable —
        // порожня БД або старий сервер.
        val last_observation: String? = null,
        // Успішні цикли за годину. errors_last_hour уже є; разом дають
        // success/error split без нового запиту.
        val runs_last_hour: Int? = null,
        // Активні (pending) alerts у БД. Розширює картину «сповіщення».
        val alerts_pending: Int? = null,
        // Найстаріше observation — «як давно збираємо».
        val collecting_since: String? = null,
    )

    @Serializable
    data class TelemetryCert(
        val days_left: Int? = null,
        val issuer: String? = null,
        // Помилка ssl-handshake з host-snapshot (напр. «handshake failed»).
        // Nullable — все ок або старий сервер.
        val error: String? = null,
    )

    @Serializable
    data class TelemetryBackups(
        val age_hours: Double? = null,
        val stale: Boolean = false,
        // Unix epoch останнього запуску (з host-snapshot). Nullable — копії
        // ніколи не запускались або старий сервер.
        val last_run: Long? = null,
    )

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

    /** Canonical перелік активних (pending) alert'ів для reconciliation (A-02). */
    @Serializable
    data class ActiveAlerts(
        val threshold: List<Long> = emptyList(),
        val eta: List<Long> = emptyList(),
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

    /** Сервер повертає secret ЄДИНИЙ раз — у відповідь на POST /devices. */
    @Serializable
    private data class DeviceOut(val device_id: String, val device_secret: String)

    @Serializable
    private data class TokenIn(val fcm_token: String)

    /**
     * Додає до запиту обидва заголовки автентифікації installation. Одного
     * X-Device-Id для стан-змінних викликів сервер більше не приймає
     * (закриття AUTH-1).
     */
    private fun io.ktor.client.request.HttpRequestBuilder.auth(
        creds: DeviceStore.Credentials
    ) {
        header("X-Device-Id", creds.deviceId)
        header("X-Device-Secret", creds.deviceSecret)
    }

    @Serializable
    private data class SubscriptionIn(val checkpoint_id: Int, val threshold: Int)

    @Serializable
    private data class EtaTargetIn(
        val checkpoint_id: Int,
        val target_at: String,
        val tolerance_seconds: Int = 900,
    )

    suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials {
        val out = client.post("$base/devices") {
            contentType(ContentType.Application.Json)
            setBody(DeviceIn(fcmToken))
        }.body<DeviceOut>()
        return DeviceStore.Credentials(out.device_id, out.device_secret)
    }

    suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
        client.put("$base/devices/token") {
            auth(creds)
            contentType(ContentType.Application.Json)
            setBody(TokenIn(fcmToken))
        }
    }

    suspend fun checkpoints(): List<Checkpoint> = client.get("$base/checkpoints").body()

    suspend fun workload(): List<Workload> = client.get("$base/workload").body()

    /** Телеметрія доступна лише адмін-пристроям; для решти сервер віддає 403. */
    suspend fun telemetry(creds: DeviceStore.Credentials): Telemetry =
        client.get("$base/admin/telemetry") { auth(creds) }.body()

    suspend fun forecast(checkpointId: Int, hours: Int = 24): Forecast =
        client.get("$base/forecast/$checkpointId?hours=$hours").body()

    suspend fun subscriptions(creds: DeviceStore.Credentials): List<Subscription> =
        client.get("$base/subscriptions") { auth(creds) }.body()

    suspend fun subscribe(creds: DeviceStore.Credentials, checkpointId: Int, threshold: Int) {
        client.post("$base/subscriptions") {
            auth(creds)
            contentType(ContentType.Application.Json)
            setBody(SubscriptionIn(checkpointId, threshold))
        }
    }

    suspend fun unsubscribe(creds: DeviceStore.Credentials, subscriptionId: Long) {
        client.delete("$base/subscriptions/$subscriptionId") { auth(creds) }
    }

    suspend fun etaTargets(creds: DeviceStore.Credentials): List<EtaTarget> =
        client.get("$base/eta-targets") { auth(creds) }.body()

    /** Canonical pending-стан для reconciliation. 401/5xx/offline кидають —
     * викликач (NotificationReconciler) на будь-якому винятку нічого не гасить. */
    suspend fun activeAlerts(creds: DeviceStore.Credentials): ActiveAlerts =
        client.get("$base/active-alerts") { auth(creds) }.body()

    suspend fun deleteEtaTarget(creds: DeviceStore.Credentials, targetId: Long) {
        client.delete("$base/eta-targets/$targetId") { auth(creds) }
    }

    suspend fun createEtaTarget(
        creds: DeviceStore.Credentials, checkpointId: Int, targetAtIso: String
    ) {
        client.post("$base/eta-targets") {
            auth(creds)
            contentType(ContentType.Application.Json)
            setBody(EtaTargetIn(checkpointId, targetAtIso))
        }
    }

    /** Кнопка «ОК». Після неї сервер припиняє повтори. */
    suspend fun ack(creds: DeviceStore.Credentials, alertId: Long, kind: String) {
        ackWith(client, creds, alertId, kind)
    }

    internal suspend fun ackWith(
        client: HttpClient,
        creds: DeviceStore.Credentials,
        alertId: Long,
        kind: String,
        requestTimeoutMs: Long = Timeouts.ACK_REQUEST_MS,
    ) {
        val path = if (kind == "eta") "eta-alerts" else "alerts"
        client.post("$base/$path/$alertId/ack") {
            auth(creds)
            timeout { requestTimeoutMillis = requestTimeoutMs }
        }
    }
}
