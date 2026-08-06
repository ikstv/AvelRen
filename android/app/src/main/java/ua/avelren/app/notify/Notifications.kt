package ua.avelren.app.notify

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import ua.avelren.app.MainActivity
import ua.avelren.app.R

/**
 * Сповіщення, яке не зникає саме.
 *
 * Вимога: воно триває, доки користувач не натисне «ОК». Досягається трьома
 * речами разом:
 *   1. `setOngoing(true)` — не змахується пальцем і не гасне по «очистити все»;
 *   2. `CATEGORY_ALARM` + канал з IMPORTANCE_HIGH — звук і показ поверх;
 *   3. сервер повторює пуш кожні 5 хвилин, доки немає підтвердження.
 *
 * Третій пункт головний: саме він робить сповіщення стійким до
 * перезавантаження телефона й вбивства застосунку. Стан тримає сервер.
 *
 * Повний екран (USE_FULL_SCREEN_INTENT) свідомо не використовуємо: з 22 січня
 * 2025 він за замовчуванням дозволений лише застосункам дзвінків і будильників.
 */
object Notifications {

    const val CHANNEL_ID = "avelren_alerts"

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

    fun show(context: Context, alertId: Long, kind: String, title: String, body: String) {
        ensureChannel(context)

        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

        val ackIntent = Intent(context, AckReceiver::class.java).apply {
            putExtra(AckReceiver.EXTRA_ALERT_ID, alertId)
            putExtra(AckReceiver.EXTRA_KIND, kind)
        }
        val ackPending = PendingIntent.getBroadcast(
            context, alertId.toInt(), ackIntent, flags
        )

        val openPending = PendingIntent.getActivity(
            context, alertId.toInt(),
            Intent(context, MainActivity::class.java),
            flags,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            // Не змахується — гасне лише кнопкою «ОК».
            .setOngoing(true)
            .setAutoCancel(false)
            .setContentIntent(openPending)
            .addAction(0, context.getString(R.string.ok), ackPending)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()

        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            NotificationManagerCompat.from(context).areNotificationsEnabled()
        ) {
            NotificationManagerCompat.from(context).notify(alertId.toInt(), notification)
        }
    }

    fun cancel(context: Context, alertId: Long) {
        NotificationManagerCompat.from(context).cancel(alertId.toInt())
    }
}
