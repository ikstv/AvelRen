package ua.avelren.app.notify

import android.content.Context
import java.time.Instant
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

interface SurgePersistence {
    fun load(): String?
    fun save(value: String): Boolean
}

private class PreferencesSurgePersistence(context: Context) : SurgePersistence {
    private val prefs = context.applicationContext.getSharedPreferences("avelren_surge", Context.MODE_PRIVATE)
    override fun load(): String? = prefs.getString("ledger", null)
    override fun save(value: String): Boolean = prefs.edit().putString("ledger", value).commit()
}

@Serializable
private data class LocalAlert(
    val acknowledged: Boolean = false,
    val cancelled: Boolean = false,
    val pendingAck: Boolean = false,
    val ordinal: Long = 0,
    val attempts: Set<String> = emptySet(),
    val checkpointId: Int = 0,
    val kind: String = "",
    val expiresAt: String? = null,
)

@Serializable
private data class LocalLedger(val alerts: Map<Long, LocalAlert> = emptyMap(), val voiceEnabled: Boolean = false, val voiceProblem: String? = null)

/** Each operation reloads durable state under one process lock across all store instances. */
class SurgeLocalStore(private val persistence: SurgePersistence) {
    constructor(context: Context) : this(PreferencesSurgePersistence(context))
    private fun read(): LocalLedger {
        val raw = persistence.load() ?: return LocalLedger()
        return json.decodeFromString<LocalLedger>(raw)
    }
    private fun write(state: LocalLedger): Boolean = persistence.save(json.encodeToString(state))
    private fun modify(block: (LocalLedger) -> LocalLedger): Boolean = synchronized(lock) {
        runCatching { write(block(read())) }.getOrDefault(false)
    }
    fun acknowledge(alertId: Long): Boolean = modify { state ->
        val alert = state.alerts[alertId] ?: LocalAlert()
        state.copy(alerts = state.alerts + (alertId to alert.copy(acknowledged = true, pendingAck = true)))
    }
    fun isAcknowledged(alertId: Long): Boolean = synchronized(lock) {
        runCatching { read().alerts[alertId]?.acknowledged == true }.getOrDefault(true)
    }
    fun isBlocked(alertId: Long): Boolean = synchronized(lock) {
        runCatching { read().alerts[alertId]?.let { it.acknowledged || it.cancelled } == true }.getOrDefault(true)
    }
    fun pendingAcks(): Set<Long> = synchronized(lock) {
        runCatching { read().alerts.filterValues { it.pendingAck }.keys }.getOrDefault(emptySet())
    }
    fun confirmAck(alertId: Long): Boolean = modify { state ->
        val alert = state.alerts[alertId] ?: return@modify state
        state.copy(alerts = state.alerts + (alertId to alert.copy(pendingAck = false)))
    }
    fun cancel(alertId: Long): Boolean = modify { state ->
        val alert = state.alerts[alertId] ?: LocalAlert()
        state.copy(alerts = state.alerts + (alertId to alert.copy(cancelled = true)))
    }
    fun voiceEnabled(): Boolean = synchronized(lock) { runCatching { read().voiceEnabled }.getOrDefault(false) }
    fun setVoiceEnabled(enabled: Boolean): Boolean = modify { it.copy(voiceEnabled = enabled, voiceProblem = null) }
    fun voiceProblem(): String? = synchronized(lock) { runCatching { read().voiceProblem }.getOrDefault("tts_unavailable") }
    fun setVoiceProblem(reason: String?): Boolean = modify { it.copy(voiceProblem = reason) }
    fun forecastAlerts(checkpointId: Int): Set<Long> = synchronized(lock) {
        runCatching { read().alerts.filterValues {
            it.kind == "surge_forecast" && it.checkpointId == checkpointId && !it.cancelled
        }.keys }.getOrDefault(emptySet())
    }
    fun activeFact(checkpointId: Int, now: Instant): Boolean = synchronized(lock) {
        runCatching { read().alerts.values.any {
            it.kind == "surge_started" && it.checkpointId == checkpointId && !it.cancelled &&
                it.expiresAt?.let { value -> Instant.parse(value) > now } == true
        } }.getOrDefault(true)
    }
    fun claimAttempt(payload: SurgePayload, now: Instant): Boolean = synchronized(lock) {
        if (!SurgeDeliveryPolicy.shouldPresent(payload, now)) return@synchronized false
        runCatching {
            val state = read()
            val alert = state.alerts[payload.alertId] ?: LocalAlert()
            if (alert.acknowledged || alert.cancelled || payload.attemptId in alert.attempts ||
                payload.ordinal <= alert.ordinal) return@runCatching false
            if (payload.kind == "surge_forecast" && activeFact(payload.checkpointId, now))
                return@runCatching false
            val next = alert.copy(ordinal = payload.ordinal, attempts = alert.attempts + payload.attemptId,
                checkpointId = payload.checkpointId, kind = payload.kind, expiresAt = payload.expiresAt)
            val previous = if (payload.kind == "surge_started") state.alerts.mapValues { (_, old) ->
                if (old.kind == "surge_forecast" && old.checkpointId == payload.checkpointId)
                    old.copy(cancelled = true) else old
            } else state.alerts
            write(state.copy(alerts = previous + (payload.alertId to next)))
        }.getOrDefault(false)
    }
    companion object {
        private val lock = Any()
        private val json = Json { ignoreUnknownKeys = true }
    }
}
