package ua.avelren.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.time.Instant
import java.util.UUID
import ua.avelren.app.notify.*

/** Debug-only, enabled solely in isolated QA manifests. Never registers or ACKs the server. */
class SystemVoiceQaReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (context.packageName !in setOf("ua.avelren.app.preview", "ua.avelren.app.pushqa")) return
        val id = intent.getLongExtra("alert_id", -1)
        if (id <= 0) return
        val kind = intent.getStringExtra("kind") ?: "surge_forecast"
        if (kind !in surgeKinds) return
        val store = SurgeLocalStore(context)
        when (intent.getStringExtra("mode")) {
            "cancel", "ack" -> {
                val saved = if (intent.getStringExtra("mode") == "ack") store.acknowledge(id) else store.cancel(id)
                if (saved) SurgeVoiceDelivery.cancel(context, kind, id)
                return
            }
        }
        val now = Instant.now()
        val data = mapOf("type" to kind, "surge_alert_id" to id.toString(),
            "attempt_id" to (intent.getStringExtra("attempt_id") ?: UUID.randomUUID().toString()),
            "attempt_ordinal" to intent.getLongExtra("ordinal", 1).toString(),
            "attempt_created_at" to now.minusSeconds(1).toString(),
            "expires_at" to now.plusSeconds(intent.getLongExtra("ttl", 120)).toString(),
            "checkpoint_id" to intent.getIntExtra("checkpoint_id", 17).toString(),
            "title" to (intent.getStringExtra("title") ?: "Чоп"),
            "body" to "Локальна перевірка системного голосу")
        val payload = SurgePayload.fromData(data) ?: return
        val forecasts = if (kind == "surge_started") store.forecastAlerts(payload.checkpointId) else emptySet()
        if (!store.claimAttempt(payload, now)) { Log.i("AvelRen/SystemVoiceQA", "claim_refused id=$id"); return }
        forecasts.forEach { SurgeVoiceDelivery.cancel(context, "surge_forecast", it) }
        SurgeVoiceDelivery.present(context, payload, allowVoice = intent.getBooleanExtra("allow_voice", true))
        Log.i("AvelRen/SystemVoiceQA", "claimed id=$id kind=$kind")
    }
}
