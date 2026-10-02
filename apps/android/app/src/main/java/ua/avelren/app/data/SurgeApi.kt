package ua.avelren.app.data

import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.android.Android
import io.ktor.client.plugins.ClientRequestException
import io.ktor.client.request.*
import io.ktor.client.plugins.timeout
import io.ktor.http.*
import kotlinx.serialization.Serializable
import ua.avelren.app.BuildConfig

@Serializable
data class SurgeCheckpoint(
    val checkpoint_id: Int, val title: String,
    val country_name: String? = null, val flag_emoji: String? = null,
    val forecast_supported: Boolean = false, val fact_supported: Boolean = false,
    val data_fresh: Boolean = false, val observed_at: String? = null,
)
@Serializable
data class SurgeStatus(
    val checkpoint_id: Int, val status: String,
    val reason: String? = null, val issued_at: String? = null,
    val window_start: String? = null, val window_end: String? = null,
    val expires_at: String? = null, val model_version: String? = null,
    val growth_5m: Int? = null, val experimental: Boolean = true,
    val forecast_supported: Boolean = false,
)
@Serializable
data class SurgeAlert(
    val surge_alert_id: Long, val event_id: Long, val checkpoint_id: Int,
    val kind: String, val expires_at: String, val title: String, val body: String,
    val growth_5m: Int? = null, val experimental: Boolean = true,
)
@Serializable
data class SurgeSubscription(
    val checkpoint_id: Int, val title: String,
    val forecast_enabled: Boolean, val fact_enabled: Boolean,
    val alerts: List<SurgeAlert> = emptyList(),
)
@Serializable
private data class SurgeSubscriptionIn(val forecast_enabled: Boolean, val fact_enabled: Boolean)

class SurgeApi(private val client: HttpClient = Api.clientFor(Android.create()),
    private val base: String = BuildConfig.API_BASE_URL) {
    suspend fun checkpoints(): List<SurgeCheckpoint> = client.get("$base/surge/checkpoints").body()
    suspend fun snapshot(checkpointId: Int): SurgeStatus = client.get("$base/surge/$checkpointId").body()
    suspend fun subscriptions(creds: DeviceStore.Credentials): List<SurgeSubscription> =
        client.get("$base/surge-subscriptions") { auth(creds) }.body()
    suspend fun setSubscription(creds: DeviceStore.Credentials, checkpointId: Int, forecast: Boolean, fact: Boolean) {
        client.put("$base/surge-subscriptions/$checkpointId") {
            auth(creds)
            contentType(ContentType.Application.Json)
            setBody(SurgeSubscriptionIn(forecast, fact))
        }
    }
    suspend fun removeSubscription(creds: DeviceStore.Credentials, checkpointId: Int) {
        client.delete("$base/surge-subscriptions/$checkpointId") { auth(creds) }
    }
    /** 404 after recovery means this device no longer owns that old alert. */
    suspend fun ack(creds: DeviceStore.Credentials, alertId: Long) {
        try {
            client.post("$base/surge-alerts/$alertId/ack") {
                auth(creds)
                timeout { requestTimeoutMillis = Timeouts.ACK_REQUEST_MS }
            }
        } catch (e: ClientRequestException) {
            if (e.response.status != HttpStatusCode.NotFound) throw e
        }
    }
    private fun HttpRequestBuilder.auth(creds: DeviceStore.Credentials) {
        header("X-Device-Id", creds.deviceId)
        header("X-Device-Secret", creds.deviceSecret)
    }
}
