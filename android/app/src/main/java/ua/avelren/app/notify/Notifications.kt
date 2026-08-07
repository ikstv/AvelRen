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
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import ua.avelren.app.MainActivity
import ua.avelren.app.R

/**
 * З Android 13 (TIRAMISU) показ сповіщень — це runtime-permission
 * POST_NOTIFICATIONS. `areNotificationsEnabled()` формально повертає той самий
 * стан, але lint читає саме @RequiresPermission-анотацію: без явного
 * checkSelfPermission() перед notify() build падає з MissingPermission.
 * Це не косметика — permission міг бути відкликаний після старту процесу.
 */
private fun canPostNotifications(context: Context): Boolean {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
    return ContextCompat.checkSelfPermission(
        context, Manifest.permission.POST_NOTIFICATIONS
    ) == PackageManager.PERMISSION_GRANTED
}

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
    const val INFO_CHANNEL_ID = "avelren_info"

    /**
     * Глобально унікальний ID сповіщення.
     *
     * alerts.id та eta_alerts.id — незалежні послідовності БД, тож threshold №1
     * і ETA №1 з голим id перезаписували б одне одного на телефоні (знахідка
     * аудиту R-03). Простір ділиться префіксом типу.
     */
    fun notificationId(kind: String, alertId: Long): Int {
        val kindCode = when (kind) {
            "threshold" -> 1
            "eta" -> 2
            else -> 3
        }
        return kindCode * 10_000_000 + (alertId % 10_000_000).toInt()
    }

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

    // Явна перевірка POST_NOTIFICATIONS робиться в canPostNotifications(),
    // але lint читає лише анотацію @RequiresPermission на самому notify() і не
    // йде за викликом. Suppression вузьке (одна функція) і має підставу — це
    // не lint-baseline.
    @SuppressLint("MissingPermission")
    fun show(context: Context, alertId: Long, kind: String, title: String, body: String) {
        ensureChannel(context)

        val notifId = notificationId(kind, alertId)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE

        val ackIntent = Intent(context, AckReceiver::class.java).apply {
            putExtra(AckReceiver.EXTRA_ALERT_ID, alertId)
            putExtra(AckReceiver.EXTRA_KIND, kind)
        }
        // requestCode теж композитний: однаковий код з FLAG_UPDATE_CURRENT
        // підмінив би extras чужого PendingIntent.
        val ackPending = PendingIntent.getBroadcast(
            context, notifId, ackIntent, flags
        )

        val openPending = PendingIntent.getActivity(
            context, notifId,
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

        if (canPostNotifications(context)) {
            NotificationManagerCompat.from(context).notify(notifId, notification)
        }
    }

    /**
     * Інформаційне сповіщення (health-тривоги сторожа).
     *
     * Це НЕ алерт із підтвердженням: воно не ongoing, змахується, без
     * AckReceiver. Раніше health ішло через show() з alert_id=0 — ongoing,
     * яке кнопкою ОК не гасилось узагалі (аудит R-03).
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
            // Стабільний ID по заголовку: «проблема» і «відновився» різні,
            // а повтори тієї самої проблеми схлопуються.
            NotificationManagerCompat.from(context)
                .notify(notificationId("health", (title.hashCode().toLong() and 0xFFFFF)), notification)
        }
    }

    fun cancel(context: Context, kind: String, alertId: Long) {
        NotificationManagerCompat.from(context).cancel(notificationId(kind, alertId))
    }
}
