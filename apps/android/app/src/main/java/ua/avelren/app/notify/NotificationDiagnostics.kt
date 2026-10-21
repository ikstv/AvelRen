package ua.avelren.app.notify

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import ua.avelren.app.data.NotificationReadiness

/** Samples settings only: never posts a notification, plays sound, or creates a channel. */
object NotificationDiagnostics {
    fun snapshot(context: Context): NotificationReadiness.Snapshot {
        val manager = context.getSystemService(NotificationManager::class.java)
        val audio = context.getSystemService(AudioManager::class.java)
        val channelRead = runCatching { requireNotNull(manager).getNotificationChannel(Notifications.CHANNEL_ID) }
        val channel = channelRead.getOrNull()
        return NotificationReadiness.Snapshot(
            runtimePermissionGranted = runCatching {
                Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                    ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            }.getOrNull(),
            appNotificationsEnabled = runCatching { NotificationManagerCompat.from(context).areNotificationsEnabled() }.getOrNull(),
            queueChannelExists = if (channelRead.isSuccess) channel != null else null,
            queueChannelImportance = channel?.importance,
            queueChannelSoundUri = channel?.sound?.toString(),
            alarmVolume = runCatching { requireNotNull(audio).getStreamVolume(AudioManager.STREAM_ALARM) }.getOrNull(),
            alarmMaxVolume = runCatching { requireNotNull(audio).getStreamMaxVolume(AudioManager.STREAM_ALARM) }.getOrNull(),
            ringerMode = runCatching { requireNotNull(audio).ringerMode }.getOrNull(),
            interruptionFilter = runCatching { requireNotNull(manager).currentInterruptionFilter }.getOrNull(),
        )
    }
}
