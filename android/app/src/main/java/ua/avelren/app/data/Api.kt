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
 * Client for our API.
 *
 * There is not, and cannot be, any call to echerha.gov.ua here — the app talks
 * exclusively to its own server (see AGENTS.md, rule 1).
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
        // Without this, Ktor 3 returns non-2xx as "success" — calls without body<>()
        // (updateToken, ack, delete) would not notice a 401 at all, and after a DB
        // restore the client would fall into an endless 401 loop without
        // re-registration (NEW-AUTH-2). Now any 4xx throws ClientRequestException,
        // 5xx — ServerResponseException.
        expectSuccess = true
    }

    private val base = BuildConfig.API_BASE_URL

    /**
     * Recognizes a 401 anywhere in an API call. `AvelRenApp` and
     * `AvelRenMessagingService` use this to clear the stored credentials and
     * register again — the typical DB-restore scenario. Ktor throws a
     * `ClientRequestException` both on a 4xx with body-decode and on a 4xx
     * without a body — this is a single handling point.
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
        // The actual measurement time (server observation time). Nullable — so that
        // old fixtures/JSON without the field stay compatible. We compute freshness
        // from it, not from the HTTP request time (AND-4).
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
        // load_5m comes from the host snapshot (PR-A). Nullable — an old server
        // without the field keeps parsing.
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
        // Available package updates. null (default) = the check failed or an old
        // server without the field; 0 = checked, no updates. The distinction
        // matters: 0 would hide a probe failure behind the look of a healthy host.
        val updates_pending: Int? = null,
        val updates_security: Int? = null,
        // Host-snapshot freshness: null on an old server, a number — age in seconds.
        val snapshot_age_seconds: Int? = null,
        // The server itself sets true if the snapshot is > 5 min old or gone. When
        // true, telemetry_snapshot_stale has already been added to problems — here
        // we duplicate it as an explicit boolean signal for the Host section.
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
        // The time of the last observation (ISO-8601 from the server). The source
        // of truth for pipeline "freshness" — we compute age on the client from it.
        // Nullable — an empty DB or an old server.
        val last_observation: String? = null,
        // Successful cycles per hour. errors_last_hour already exists; together
        // they give a success/error split without a new request.
        val runs_last_hour: Int? = null,
        // Active (pending) alerts in the DB. Broadens the "notifications" picture.
        val alerts_pending: Int? = null,
        // The oldest observation — "how long we have been collecting".
        val collecting_since: String? = null,
    )

    @Serializable
    data class TelemetryCert(
        val days_left: Int? = null,
        val issuer: String? = null,
        // An ssl-handshake error from the host snapshot (e.g. "handshake failed").
        // Nullable — all is well or an old server.
        val error: String? = null,
    )

    @Serializable
    data class TelemetryBackups(
        val age_hours: Double? = null,
        val stale: Boolean = false,
        // Unix epoch of the last run (from the host snapshot). Nullable — backups
        // never ran or an old server.
        val last_run: Long? = null,
    )

    // ---- PR-B: per-container and global extensions ----
    //
    // All new fields are nullable / have a default: an old server (without PR-B)
    // still parses with the same client; a new server with PR-B but an old client
    // also works (ignoreUnknownKeys).

    @Serializable
    data class TelemetryService(
        val name: String,
        val status: String? = null,
        val health: String? = null,
        val started_at: String? = null,
        val restart_count: Int? = null,
        val exit_code: Int? = null,
        val oom_killed: Boolean? = null,
        val image: String? = null,
    )

    @Serializable
    data class TelemetryDocker(
        val daemon_version: String? = null,
        val compose_version: String? = null,
    )

    @Serializable
    data class TelemetryInodes(
        val total: Long? = null,
        val used: Long? = null,
        val used_percent: Int? = null,
    )

    @Serializable
    data class TelemetryUpstream(
        val base_url: String? = null,
        val workload_url: String? = null,
        val vehicle_type: Int? = null,
        val poll_interval_seconds: Int? = null,
    )

    @Serializable
    data class TelemetryLastRun(
        val time: String? = null,
        val http_status: Int? = null,
        val duration_ms: Int? = null,
        val rows_written: Int? = null,
        val error: String? = null,
        val derived_processed_at: String? = null,
        val derived_error: String? = null,
    )

    @Serializable
    data class TelemetryLastSuccess(
        val time: String? = null,
        val http_status: Int? = null,
        val duration_ms: Int? = null,
        val rows_written: Int? = null,
    )

    @Serializable
    data class TelemetryVersion(
        val app_version: String? = null,
        val git_sha: String? = null,
        val migrations_version: String? = null,
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
        // PR-B — everything optional for compatibility with an old server.
        val services: List<TelemetryService> = emptyList(),
        val docker: TelemetryDocker? = null,
        val inodes: TelemetryInodes? = null,
        val upstream: TelemetryUpstream? = null,
        val last_collector_run: TelemetryLastRun? = null,
        val last_collector_success: TelemetryLastSuccess? = null,
        val version: TelemetryVersion? = null,
    )

    /** Canonical list of active (pending) alerts for reconciliation (A-02). */
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
        /** collecting — no forecast yet; preliminary — provisional; ready — final. */
        val status: String,
        val weeks_collected: Double,
        val weeks_needed: Int,
        val ready_at: String? = null,
        val points: List<ForecastPoint> = emptyList(),
    )

    @Serializable
    private data class DeviceIn(val fcm_token: String, val platform: String = "android")

    /** The server returns the secret ONLY once — in response to POST /devices. */
    @Serializable
    private data class DeviceOut(val device_id: String, val device_secret: String)

    @Serializable
    private data class TokenIn(val fcm_token: String)

    /**
     * Adds both installation authentication headers to the request. The server no
     * longer accepts X-Device-Id alone for state-changing calls (closing AUTH-1).
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

    /** Telemetry is available only to admin devices; for the rest the server returns 403. */
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

    /** Canonical pending state for reconciliation. 401/5xx/offline throw —
     * the caller (NotificationReconciler) dismisses nothing on any exception. */
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

    /** The "OK" button. After it the server stops retrying. */
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
