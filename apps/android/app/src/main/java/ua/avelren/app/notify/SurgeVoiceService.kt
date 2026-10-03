package ua.avelren.app.notify

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import java.time.Instant
import ua.avelren.app.R

/** Short, user-enabled speech playback; never sticky or started from boot. */
class SurgeVoiceService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val queue = SurgeVoiceQueue()
    private var tts: TextToSpeech? = null
    private var ready = false
    private var closing = false
    private var current: SurgePayload? = null
    private lateinit var store: SurgeLocalStore
    private lateinit var audio: AudioManager
    private var focus: AudioFocusRequest? = null
    private val finishTimeout = Runnable { finishService() }
    private val initTimeout = Runnable { if (!ready) { store.setVoiceProblem("tts_unavailable"); finishService() } }
    private val speechTimeout = Runnable { finishService() }
    private val recheck = object : Runnable {
        override fun run() {
            if (closing) return
            current?.let { if (!canSpeak(it)) { tts?.stop(); complete(it.attemptId) } }
            if (!closing) handler.postDelayed(this, 250)
        }
    }

    override fun onCreate() {
        super.onCreate()
        store = SurgeLocalStore(this)
        audio = getSystemService(AudioManager::class.java)
        active = this
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(
                VOICE_CHANNEL, "Озвучення зростання черги", NotificationManager.IMPORTANCE_LOW,
            ).apply { setSound(null, null) })
            val notification = NotificationCompat.Builder(this, VOICE_CHANNEL)
                .setSmallIcon(R.drawable.ic_notification).setContentTitle("AvelRen")
                .setContentText("Озвучення повідомлення про чергу").setOngoing(true).setSilent(true).build()
            // Foreground BEFORE any TTS initialization or audio-focus request.
            ServiceCompat.startForeground(this, VOICE_ID, notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK)
        } catch (e: RuntimeException) {
            Log.w(TAG, "foreground rejected: ${e.javaClass.simpleName}")
            store.setVoiceProblem("background_limited")
            finishService()
            return
        }
        handler.postDelayed(finishTimeout, 60_000)
        handler.postDelayed(initTimeout, 10_000)
        handler.postDelayed(recheck, 250)
        try {
            tts = TextToSpeech(this) { result -> handler.post { initialize(result) } }
        } catch (_: RuntimeException) { store.setVoiceProblem("tts_unavailable"); finishService() }
    }

    private fun initialize(result: Int) {
        if (closing) return
        val engine = tts ?: return finishService()
        if (result != TextToSpeech.SUCCESS) { store.setVoiceProblem("tts_unavailable"); return finishService() }
        try {
            val voices = engine.voices.orEmpty().filter {
                it.locale.language == "uk" && !it.isNetworkConnectionRequired &&
                    TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in it.features.orEmpty()
            }
            // Restore the original Ukrainian timbre requested by the owner.
            val voice = voices.firstOrNull { it.name == "uk-UA-language" }
                ?: voices.firstOrNull { it.name == engine.defaultVoice?.name } ?: voices.sortedBy { it.name }.firstOrNull()
            if (voice == null || engine.setVoice(voice) != TextToSpeech.SUCCESS) {
                Log.i(TAG, "installed Ukrainian voice unavailable")
                store.setVoiceProblem("uk_unavailable")
                finishService()
                return
            }
            engine.setSpeechRate(0.88f)
            engine.setPitch(1f)
            engine.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) { }
                override fun onDone(utteranceId: String?) { handler.post { complete(utteranceId) } }
                @Deprecated("Platform callback")
                override fun onError(utteranceId: String?) { handler.post { complete(utteranceId) } }
                override fun onError(utteranceId: String?, errorCode: Int) { handler.post { complete(utteranceId) } }
            })
            store.setVoiceProblem(null)
            ready = true
            handler.removeCallbacks(initTimeout)
            speakNext()
        } catch (_: RuntimeException) { store.setVoiceProblem("tts_unavailable"); finishService() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (closing) return START_NOT_STICKY
        val payload = intent?.let { readPayload(it) }
        if (payload == null || !canSpeak(payload)) {
            if (current == null) finishService()
            return START_NOT_STICKY
        }
        if (payload.kind == "surge_started" && current?.let {
            it.kind == "surge_forecast" && it.checkpointId == payload.checkpointId
        } == true) {
            current = null
            tts?.stop()
            handler.removeCallbacks(speechTimeout)
        }
        if (current?.attemptId != payload.attemptId) queue.offer(payload, Instant.now())
        if (ready) speakNext()
        return START_NOT_STICKY
    }

    private fun canSpeak(payload: SurgePayload): Boolean =
        SurgeDeliveryPolicy.shouldPresent(payload, Instant.now()) && store.voiceEnabled() &&
            !store.isBlocked(payload.alertId) && Notifications.surgeChannelAllowed(this) &&
            audio.ringerMode == AudioManager.RINGER_MODE_NORMAL &&
            getSystemService(NotificationManager::class.java).currentInterruptionFilter == NotificationManager.INTERRUPTION_FILTER_ALL &&
            !(payload.kind == "surge_forecast" && store.activeFact(payload.checkpointId, Instant.now()))

    private fun speakNext() {
        if (closing || !ready || current != null) return
        val next = queue.next(Instant.now(), store::isBlocked) ?: return finishService()
        if (!canSpeak(next)) return speakNext()
        try {
            if (focus == null) {
                val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                    .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    .setOnAudioFocusChangeListener({ change ->
                        if (change < 0) finishService()
                    }, handler).build()
                if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
                    store.setVoiceProblem("audio_busy")
                    return finishService()
                }
                focus = request
            }
            current = next
            handler.postDelayed(speechTimeout, 30_000)
            if (tts?.speak(next.body, TextToSpeech.QUEUE_FLUSH, null, next.attemptId) != TextToSpeech.SUCCESS)
                complete(next.attemptId)
        } catch (_: RuntimeException) { store.setVoiceProblem("tts_unavailable"); finishService() }
    }

    private fun complete(id: String?) {
        if (closing || current?.attemptId != id) return
        handler.removeCallbacks(speechTimeout)
        current = null
        speakNext()
    }
    private fun cancelAlert(id: Long) {
        queue.cancel(id)
        if (current?.alertId == id) {
            current = null
            tts?.stop()
            handler.removeCallbacks(speechTimeout)
            speakNext()
        }
    }
    private fun finishService() {
        if (closing) return
        closing = true
        queue.clear()
        tts?.stop()
        stopSelf()
    }
    override fun onDestroy() {
        closing = true
        handler.removeCallbacksAndMessages(null)
        runCatching { tts?.stop() }
        runCatching { tts?.shutdown() }
        tts = null
        focus?.let { runCatching { audio.abandonAudioFocusRequest(it) } }
        focus = null
        queue.clear()
        if (active === this) active = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val TAG = "AvelRen/Voice"
        private const val VOICE_CHANNEL = "avelren_surge_voice"
        private const val VOICE_ID = 60_000_000
        @Volatile private var active: SurgeVoiceService? = null
        fun enqueue(context: Context, payload: SurgePayload) {
            try {
                val intent = Intent(context, SurgeVoiceService::class.java)
                    .putExtra("kind", payload.kind).putExtra("alert_id", payload.alertId)
                    .putExtra("attempt_id", payload.attemptId).putExtra("ordinal", payload.ordinal)
                    .putExtra("created_at", payload.createdAt).putExtra("expires_at", payload.expiresAt)
                    .putExtra("checkpoint_id", payload.checkpointId).putExtra("title", payload.title).putExtra("body", payload.body)
                ContextCompat.startForegroundService(context, intent)
            } catch (e: RuntimeException) {
                SurgeLocalStore(context).setVoiceProblem("background_limited")
                Log.i(TAG, "voice unavailable: ${e.javaClass.simpleName}")
            }
        }
        fun stopAlert(context: Context, alertId: Long) {
            active?.let { service -> service.handler.post { service.cancelAlert(alertId) } }
        }
        private fun readPayload(intent: Intent): SurgePayload? = runCatching {
            SurgePayload(intent.getStringExtra("kind") ?: return null, intent.getLongExtra("alert_id", -1),
                intent.getStringExtra("attempt_id") ?: return null, intent.getLongExtra("ordinal", -1),
                intent.getStringExtra("created_at") ?: return null, intent.getStringExtra("expires_at") ?: return null,
                intent.getIntExtra("checkpoint_id", -1), intent.getStringExtra("title") ?: return null,
                intent.getStringExtra("body") ?: return null)
        }.getOrNull()
    }
}
