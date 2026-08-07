package ua.avelren.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Зберігає `device_id`.
 *
 * Це фактично ключ доступу до підписок користувача: хто його має, той керує
 * ними. Тому шифроване сховище, а не звичайні preferences.
 */
object DeviceStore {

    private const val FILE = "avelren_secure"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_SELECTED = "selected_checkpoint"

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

    fun deviceId(context: Context): String? = prefs(context).getString(KEY_DEVICE_ID, null)

    fun saveDeviceId(context: Context, id: String) {
        prefs(context).edit().putString(KEY_DEVICE_ID, id).apply()
    }

    fun selectedCheckpoint(context: Context): Int =
        prefs(context).getInt(KEY_SELECTED, -1)

    fun saveSelectedCheckpoint(context: Context, id: Int) {
        prefs(context).edit().putInt(KEY_SELECTED, id).apply()
    }
}
