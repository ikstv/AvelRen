package ua.avelren.app.notify

import android.content.Context
import android.os.Handler
import android.os.Looper

/** Notification mutations and voice queue operations share the main looper. */
object SurgeVoiceDelivery {
    private val handler = Handler(Looper.getMainLooper())
    private fun main(block: () -> Unit) { if (Looper.myLooper() == Looper.getMainLooper()) block() else handler.post(block) }
    fun cancel(context: Context, kind: String, alertId: Long) = main {
        Notifications.cancel(context, kind, alertId)
        SurgeVoiceService.stopAlert(context, alertId)
    }
    fun present(context: Context, payload: SurgePayload, allowVoice: Boolean) = main {
        val store = SurgeLocalStore(context)
        val voice = SurgeVoiceAssets(context).ready(VoiceSoundKey(payload.checkpointId, payload.kind))
        if (voice == null) {
            store.setVoiceProblem("voice_not_ready")
            Notifications.showSurge(context, payload, null, silent = false)
        } else {
            val state = SurgeVoiceChannels.state(context, voice)
            store.setVoiceProblem(state.problem)
            if (Notifications.showSurge(context, payload, voice, silent = true) && state.voiceAllowed) {
                if (allowVoice) SurgeVoiceService.enqueue(context, payload)
                else store.setVoiceProblem("background_limited")
            }
        }
    }
}
