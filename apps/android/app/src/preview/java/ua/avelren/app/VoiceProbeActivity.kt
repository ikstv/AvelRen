package ua.avelren.app

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import java.time.Instant
import java.util.UUID
import ua.avelren.app.notify.*

/** Debug-only adb probe; no UI button, credentials, Firebase, or network. */
class VoiceProbeActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val handler = Handler(Looper.getMainLooper())
        val scenario = intent.getStringExtra("scenario") ?: "foreground"
        handler.postDelayed({
            val now = Instant.now()
            val id = intent.getLongExtra("alert_id", 9001)
            val payload = SurgePayload("surge_forecast", id, UUID.randomUUID().toString(), 1,
                now.minusSeconds(1).toString(), now.plusSeconds(60).toString(), 17, "Чоп",
                "Можливий початок масової реєстрації на Чопі")
            val store = SurgeLocalStore(this)
            store.setVoiceEnabled(true)
            Notifications.ensureChannel(this)
            if (store.claimAttempt(payload, now)) {
                Notifications.show(this, id, payload.kind, payload.title, payload.body)
                SurgeVoiceService.enqueue(this, payload)
            }
            if (scenario == "collision") {
                Notifications.show(this, id + 10_000_000, payload.kind, payload.title, "Другий незалежний сигнал")
                handler.postDelayed({ Notifications.cancel(this, payload.kind, id) }, 100)
            }
            if (scenario == "cancel") handler.postDelayed({
                store.acknowledge(id)
                Notifications.cancel(this, payload.kind, id)
                SurgeVoiceService.stopAlert(this, id)
            }, 50)
            if (scenario == "background") finish()
        }, if (scenario == "background") 5_000 else 500)
    }
}
