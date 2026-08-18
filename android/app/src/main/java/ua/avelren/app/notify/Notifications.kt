package ua.avelren.app.notify

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import ua.avelren.app.MainActivity
import ua.avelren.app.R

/**
 * Since Android 13 (TIRAMISU), showing notifications is the POST_NOTIFICATIONS
 * runtime permission. An explicit checkSelfPermission() is also needed for lint:
 * it reads @RequiresPermission on notify() and does not follow the call.
 *
 * AND-2: the permission check alone lied on Android 8–12, where there is no
 * runtime permission, but the user could disable the app's notifications in the
 * system — then notify() silently did nothing. Now the posting path asks the same
 * truth as the UI: permission AND `areNotificationsEnabled()`.
 */
private fun canPostNotifications(context: Context): Boolean {
    val runtimeOk = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS
        ) == PackageManager.PERMISSION_GRANTED
    return runtimeOk && NotificationManagerCompat.from(context).areNotificationsEnabled()
}

/**
 * A notification that does not disappear on its own.
 *
 * Requirement: it persists until the user taps "OK". Achieved by three things
 * together:
 *   1. `setOngoing(true)` — cannot be swiped away and does not clear on "clear all";
 *   2. `CATEGORY_ALARM` + a channel with IMPORTANCE_HIGH — sound and heads-up display;
 *   3. the server repeats the push every 5 minutes until there is an acknowledgement.
 *
 * The third point is the main one: it is what makes the notification resilient to
 * a phone reboot and app kill. The server holds the state.
 *
 * We deliberately do not use full-screen (USE_FULL_SCREEN_INTENT): since 22
 * January 2025 it is allowed by default only to calling and alarm apps.
 */
object Notifications {

    const val CHANNEL_ID = "avelren_alerts"
    const val INFO_CHANNEL_ID = "avelren_info"

    // The full kind + alertId in the notification's extras. Reconciliation reads
    // these, not the display-id: notificationId() is irreversible (truncation
    // alertId % 10^7), so the full alertId cannot be recovered from it (audit A-02).
    const val EXTRA_KIND = "avelren_kind"
    const val EXTRA_ALERT_ID = "avelren_alert_id"

    /**
     * A globally unique notification ID.
     *
     * alerts.id and eta_alerts.id are independent DB sequences, so threshold #1
     * and ETA #1 with a bare id would overwrite each other on the phone (audit
     * finding R-03). The space is split by a type prefix.
     */
    fun notificationId(kind: String, alertId: Long): Int {
        val kindCode = when (kind) {
            "threshold" -> 1
            "eta" -> 2
            else -> 3
        }
        return kindCode * 10_000_000 + (alertId % 10_000_000).toInt()
    }

    /**
     * The alert channel exists but is disabled by the user (IMPORTANCE_NONE). A
     * separate case from an app-wide block: the app's notifications are allowed,
     * but the queue channel specifically is not, and we must lead to the channel
     * settings (AND-2).
     */
    fun alertChannelBlocked(context: Context): Boolean {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return false
        val channel = nm.getNotificationChannel(CHANNEL_ID) ?: return false
        return channel.importance == NotificationManager.IMPORTANCE_NONE
    }

    /** Whether the app's notifications are enabled in the system (all Android versions). */
    fun appNotificationsEnabled(context: Context): Boolean =
        NotificationManagerCompat.from(context).areNotificationsEnabled()

    /** Whether the runtime permission is granted (on < 33 it does not exist — we treat it as granted). */
    fun runtimePermissionGranted(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED

    fun ensureChannel(context: Context) {
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.alert_channel_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = context.getString(R.string.alert_channel_description)
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 500, 250, 500, 250, 500)
            setSound(
                RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build(),
            )
            lockscreenVisibility = NotificationCompat.VISIBILITY_PUBLIC
        }
        context.getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)
    }

    // The explicit POST_NOTIFICATIONS check is done in canPostNotifications(),
    // but lint reads only the @RequiresPermission annotation on notify() itself and
    // does not follow the call. The suppression is narrow (one function) and
    // justified — this is not a lint baseline.
    @SuppressLint("MissingPermission")
    fun show(context: Context, alertId: Long, kind: String, title: String, body: String) {
        ensureChannel(context)

        val notifId = notificationId(kind, alertId)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

        val ackIntent = Intent(context, AckReceiver::class.java).apply {
            putExtra(AckReceiver.EXTRA_ALERT_ID, alertId)
            putExtra(AckReceiver.EXTRA_KIND, kind)
        }
        // The requestCode is also composite: an identical code with FLAG_UPDATE_CURRENT
        // would substitute the extras of another PendingIntent.
        val ackPending = PendingIntent.getBroadcast(
            context, notifId, ackIntent, flags
        )

        val openPending = PendingIntent.getActivity(
            context, notifId,
            Intent(context, MainActivity::class.java),
            flags,
        )

        // The full key for reconciliation — right here, because the display-id is truncated.
        val extras = Bundle().apply {
            putString(EXTRA_KIND, kind)
            putLong(EXTRA_ALERT_ID, alertId)
        }

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            // Not swipeable — dismissed only by the "OK" button.
            .setOngoing(true)
            .setAutoCancel(false)
            .setContentIntent(openPending)
            .addAction(0, context.getString(R.string.ok), ackPending)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .addExtras(extras)
            .build()

        if (canPostNotifications(context)) {
            NotificationManagerCompat.from(context).notify(notifId, notification)
        }
    }

    /**
     * An informational notification (the watchdog's health alerts).
     *
     * This is NOT an alert with acknowledgement: it is not ongoing, is swipeable,
     * has no AckReceiver. Previously health went through show() with alert_id=0 —
     * ongoing, which the OK button did not dismiss at all (audit R-03).
     */
    @SuppressLint("MissingPermission")
    fun showInfo(context: Context, title: String, body: String) {
        ensureChannel(context)
        val channel = NotificationChannel(
            INFO_CHANNEL_ID,
            "Стан сервера",
            NotificationManager.IMPORTANCE_DEFAULT,
        )
        context.getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)

        val notification = NotificationCompat.Builder(context, INFO_CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setAutoCancel(true)
            .build()

        if (canPostNotifications(context)) {
            // A stable ID by title: "problem" and "recovered" are different,
            // while repeats of the same problem collapse together.
            NotificationManagerCompat.from(context)
                .notify(notificationId("health", (title.hashCode().toLong() and 0xFFFFF)), notification)
        }
    }

    fun cancel(context: Context, kind: String, alertId: Long) {
        NotificationManagerCompat.from(context).cancel(notificationId(kind, alertId))
    }
}
