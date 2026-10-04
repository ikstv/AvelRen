package ua.avelren.app.notify

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import java.time.Instant
import ua.avelren.app.BuildConfig
import ua.avelren.app.R

/** Bounded sequencer; sound belongs to SystemUI, no delivery TTS or audio focus. */
class SurgeVoiceService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val queue = SurgeVoiceQueue()
    private lateinit var store: SurgeLocalStore
    private lateinit var assets: SurgeVoiceAssets
    private lateinit var schedule: SurgeVoiceSchedule
    private var closing = false
    private var current: SurgePayload? = null
    private var nextAt = 0L
    private val deadline = Runnable { store.setVoiceProblem("voice_deadline"); finishService() }
    private val tick = object : Runnable {
        override fun run() {
            if (closing) return
            current?.let { payload ->
                if (!canSpeak(payload)) {
                    Notifications.cancel(this@SurgeVoiceService, payload.kind, payload.alertId)
                    current = null
                } else if (SystemClock.elapsedRealtime() >= nextAt) current = null
            }
            pump()
            if (!closing) handler.postDelayed(this, 250)
        }
    }
    override fun onCreate() {
        super.onCreate()
        store = SurgeLocalStore(this)
        assets = SurgeVoiceAssets(this)
        schedule = SurgeVoiceSchedule(SystemClock.elapsedRealtime())
        active = this
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(VOICE_CHANNEL, "Озвучення зростання черги", NotificationManager.IMPORTANCE_LOW)
                .apply { setSound(null, null) })
            val notification = NotificationCompat.Builder(this, VOICE_CHANNEL).setSmallIcon(R.drawable.ic_notification)
                .setContentTitle("AvelRen").setContentText("Озвучення повідомлення про чергу").setOngoing(true).setSilent(true).build()
            ServiceCompat.startForeground(this, VOICE_ID, notification,
                if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SHORT_SERVICE else 0)
        } catch (e: RuntimeException) {
            Log.w(TAG, "foreground rejected: ${e.javaClass.simpleName}")
            store.setVoiceProblem("background_limited")
            finishService()
            return
        }
        handler.postDelayed(deadline, 160_000)
        handler.postDelayed(tick, 250)
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (closing) return START_NOT_STICKY
        val payload = intent?.let(::readPayload)
        if (payload != null && canSpeak(payload)) {
            if (payload.kind == "surge_started" && current?.let {
                it.kind == "surge_forecast" && it.checkpointId == payload.checkpointId
            } == true) {
                current?.let { Notifications.cancel(this, it.kind, it.alertId) }
                current = null
            }
            if (current?.attemptId != payload.attemptId && !queue.offer(payload, Instant.now()))
                store.setVoiceProblem("voice_queue_full")
        }
        pump()
        return START_NOT_STICKY
    }
    private fun voice(payload: SurgePayload) = assets.ready(VoiceSoundKey(payload.checkpointId, payload.kind))
    private fun canSpeak(payload: SurgePayload): Boolean {
        if (!SurgeDeliveryPolicy.shouldPresent(payload, Instant.now()) || !store.voiceEnabled() || store.isBlocked(payload.alertId) ||
            (payload.kind == "surge_forecast" && store.activeFact(payload.checkpointId, Instant.now()))) return false
        val ready = voice(payload) ?: return false
        val state = SurgeVoiceChannels.state(this, ready)
        if (!state.voiceAllowed) { store.setVoiceProblem(state.problem); return false }
        val audio = getSystemService(AudioManager::class.java)
        val manager = getSystemService(NotificationManager::class.java)
        if (audio.ringerMode != AudioManager.RINGER_MODE_NORMAL ||
            manager.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL) {
            store.setVoiceProblem("notification_silent")
            return false
        }
        return true
    }
    private fun pump() {
        if (closing || current != null || SystemClock.elapsedRealtime() < nextAt) return
        while (!closing) {
            val next = queue.next(Instant.now(), store::isBlocked) ?: return finishService()
            if (!canSpeak(next)) continue
            val prepared = voice(next) ?: continue
            val now = SystemClock.elapsedRealtime()
            if (!schedule.canStart(now, prepared.durationMs)) {
                store.setVoiceProblem("voice_deadline")
                return finishService()
            }
            if (!Notifications.showSurge(this, next, prepared, silent = false)) continue
            current = next
            nextAt = schedule.reserve(SystemClock.elapsedRealtime(), prepared.durationMs)
            store.setVoiceProblem(null)
            if (BuildConfig.DEBUG) Log.i(TAG, "system_voice_started cp=${next.checkpointId} kind=${next.kind} duration_ms=${prepared.durationMs}")
            return
        }
    }
    private fun cancelAlert(id: Long) {
        queue.cancel(id)
        current?.takeIf { it.alertId == id }?.let { Notifications.cancel(this, it.kind, id); current = null }
        pump()
    }
    private fun finishService() {
        if (closing) return
        closing = true
        queue.clear()
        handler.removeCallbacksAndMessages(null)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }
    override fun onTimeout(startId: Int) { store.setVoiceProblem("voice_deadline"); finishService() }
    override fun onTimeout(startId: Int, fgsType: Int) { store.setVoiceProblem("voice_deadline"); finishService() }
    override fun onDestroy() {
        closing = true
        handler.removeCallbacksAndMessages(null)
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
                ContextCompat.startForegroundService(context, Intent(context, SurgeVoiceService::class.java)
                    .putExtra("kind", payload.kind).putExtra("alert_id", payload.alertId)
                    .putExtra("attempt_id", payload.attemptId).putExtra("ordinal", payload.ordinal)
                    .putExtra("created_at", payload.createdAt).putExtra("expires_at", payload.expiresAt)
                    .putExtra("checkpoint_id", payload.checkpointId).putExtra("title", payload.title).putExtra("body", payload.body))
            } catch (e: RuntimeException) {
                SurgeLocalStore(context).setVoiceProblem("background_limited")
                Log.i(TAG, "voice unavailable: ${e.javaClass.simpleName}")
            }
        }
        fun stopAlert(context: Context, alertId: Long) {
            active?.let { service ->
                if (Looper.myLooper() == Looper.getMainLooper()) service.cancelAlert(alertId)
                else service.handler.post { service.cancelAlert(alertId) }
            }
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
