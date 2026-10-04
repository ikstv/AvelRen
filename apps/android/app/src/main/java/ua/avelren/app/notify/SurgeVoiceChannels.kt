package ua.avelren.app.notify

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes

data class VoiceChannelState(val visible: Boolean, val voiceAllowed: Boolean, val problem: String?)

object SurgeVoiceChannelPolicy {
    fun evaluate(appAllowed: Boolean, legacyImportance: Int, legacySoundPresent: Boolean,
        voiceImportance: Int?, voiceSoundPresent: Boolean, soundMatches: Boolean): VoiceChannelState = when {
        !appAllowed || legacyImportance <= 0 -> VoiceChannelState(false, false, "notification_blocked")
        voiceImportance == null -> VoiceChannelState(true, false, "voice_not_ready")
        voiceImportance <= 0 -> VoiceChannelState(false, false, "notification_blocked")
        legacyImportance < 3 || !legacySoundPresent || (voiceImportance ?: 0) < 3 || !voiceSoundPresent ->
            VoiceChannelState(true, false, "notification_silent")
        !soundMatches -> VoiceChannelState(true, false, "voice_sound_changed")
        else -> VoiceChannelState(true, true, null)
    }
}

object SurgeVoiceChannels {
    fun id(key: VoiceSoundKey): String = "avelren_surge_voice_v1_${key.checkpointId}_${key.kind}"
    fun ensure(context: Context, voice: PreparedVoice, title: String): String {
        val assets = SurgeVoiceAssets(context)
        require(assets.ready(voice.key) == voice)
        Notifications.ensureChannel(context)
        val manager = context.getSystemService(NotificationManager::class.java)
        val id = id(voice.key)
        if (manager.getNotificationChannel(id) == null) {
            val kind = if (voice.key.kind == "surge_forecast") "Прогноз" else "Початок зростання"
            manager.createNotificationChannel(NotificationChannel(id, "$title — $kind", NotificationManager.IMPORTANCE_HIGH).apply {
                setSound(assets.soundUri(voice.key), AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            })
        }
        return id
    }
    fun state(context: Context, voice: PreparedVoice): VoiceChannelState {
        val manager = context.getSystemService(NotificationManager::class.java)
        val legacy = manager.getNotificationChannel(Notifications.SURGE_CHANNEL_ID)
        val channel = manager.getNotificationChannel(id(voice.key))
        return SurgeVoiceChannelPolicy.evaluate(Notifications.runtimePermissionGranted(context) && Notifications.appNotificationsEnabled(context),
            legacy?.importance ?: 0, legacy?.sound != null, channel?.importance, channel?.sound != null,
            channel?.sound == SurgeVoiceAssets(context).soundUri(voice.key))
    }
}
