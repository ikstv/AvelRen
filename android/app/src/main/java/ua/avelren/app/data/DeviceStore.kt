package ua.avelren.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Зберігає облікові дані installation: пару `device_id + device_secret`.
 *
 * Раніше сервер приймав лише X-Device-Id, і UUID сам по собі відкривав
 * підписки — це компрометувалось, якщо FCM-токен потрапляв не в ті руки
 * (аудит AUTH-1). Тепер сервер вимагає X-Device-Secret; знання одного лише
 * UUID нічого не дає, і зберігати обидва треба з шифруванням.
 *
 * `Credentials` — атомарна одиниця: якщо є id, то мусить бути й secret. Без
 * пари ніяких запитів робити не можна.
 */
object DeviceStore {

    data class Credentials(val deviceId: String, val deviceSecret: String)

    private const val FILE = "avelren_secure"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_DEVICE_SECRET = "device_secret"
    private const val KEY_SELECTED = "selected_checkpoint"
    // AND-2. Свідомо НЕ чіпається clearCredentials(): історія запитів дозволу
    // не має скидатися при 401-перереєстрації installation — інакше після
    // кожного DB restore ми знову питали б дозвіл у того, хто вже відмовив.
    private const val KEY_NOTIF_ASKED = "notif_asked"
    private const val KEY_NOTIF_DENIED = "notif_denied_once"
    private const val KEY_NOTIF_GRANTED = "notif_ever_granted"

    private var prefs: SharedPreferences? = null

    private fun prefs(context: Context): SharedPreferences = prefs ?: run {
        val key = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            FILE,
            key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        ).also { prefs = it }
    }

    fun credentials(context: Context): Credentials? {
        val p = prefs(context)
        val id = p.getString(KEY_DEVICE_ID, null) ?: return null
        val secret = p.getString(KEY_DEVICE_SECRET, null) ?: return null
        return Credentials(id, secret)
    }

    fun saveCredentials(context: Context, creds: Credentials) {
        prefs(context).edit()
            .putString(KEY_DEVICE_ID, creds.deviceId)
            .putString(KEY_DEVICE_SECRET, creds.deviceSecret)
            .apply()
    }

    /**
     * Очистити збережену пару. Викликаємо, коли сервер сказав 401 на
     * гарантовано наші заголовки — installation більше не існує (наприклад,
     * DB restore відкотив реєстрацію). Наступний старт створить нову.
     */
    fun clearCredentials(context: Context) {
        prefs(context).edit()
            .remove(KEY_DEVICE_ID)
            .remove(KEY_DEVICE_SECRET)
            .apply()
    }

    fun notificationHistory(context: Context): NotificationPermission.History {
        val p = prefs(context)
        return NotificationPermission.History(
            asked = p.getBoolean(KEY_NOTIF_ASKED, false),
            deniedOnce = p.getBoolean(KEY_NOTIF_DENIED, false),
            everGranted = p.getBoolean(KEY_NOTIF_GRANTED, false),
        )
    }

    fun saveNotificationHistory(context: Context, h: NotificationPermission.History) {
        prefs(context).edit()
            .putBoolean(KEY_NOTIF_ASKED, h.asked)
            .putBoolean(KEY_NOTIF_DENIED, h.deniedOnce)
            .putBoolean(KEY_NOTIF_GRANTED, h.everGranted)
            .apply()
    }

    fun selectedCheckpoint(context: Context): Int =
        prefs(context).getInt(KEY_SELECTED, -1)

    fun saveSelectedCheckpoint(context: Context, id: Int) {
        prefs(context).edit().putInt(KEY_SELECTED, id).apply()
    }
}
