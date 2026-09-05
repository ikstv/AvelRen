package ua.avelren.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Stores the installation credentials: the `device_id + device_secret` pair.
 *
 * Previously the server accepted only X-Device-Id, and the UUID alone unlocked
 * subscriptions — this was compromisable if the FCM token fell into the wrong
 * hands (audit AUTH-1). Now the server requires X-Device-Secret; knowing the
 * UUID alone gives nothing, and both must be stored encrypted.
 *
 * `Credentials` is an atomic unit: if there is an id, there must be a secret
 * too. Without the pair, no requests can be made.
 */
object DeviceStore {

    data class Credentials(val deviceId: String, val deviceSecret: String)

    private const val FILE = "avelren_secure"
    private const val KEY_DEVICE_ID = "device_id"
    private const val KEY_DEVICE_SECRET = "device_secret"
    private const val KEY_SELECTED = "selected_checkpoint"
    private const val KEY_PENDING_FCM_TOKEN = "pending_fcm_token"
    // AND-2. Deliberately NOT touched by clearCredentials(): the permission-request
    // history must not reset on a 401 installation re-registration — otherwise after
    // every DB restore we would again ask for permission from someone who already refused.
    private const val KEY_NOTIF_ASKED = "notif_asked"
    private const val KEY_NOTIF_DENIED = "notif_denied_once"
    private const val KEY_NOTIF_GRANTED = "notif_ever_granted"
    // Marker of the one-time legacy migration (upgrade from a pre-AND-2 version).
    // Likewise NOT touched by clearCredentials(): the migration must be done exactly
    // once per installation, regardless of a 401 re-registration.
    private const val KEY_NOTIF_MIGRATED = "notif_legacy_migrated"

    // #117: the user has read the background-delivery hint and closed it. Also NOT
    // touched by clearCredentials(): re-registering after a 401 is not a reason to
    // show someone the same advice about their phone's battery settings again.
    private const val KEY_BG_HINT_DISMISSED = "bg_delivery_hint_dismissed"

    @Volatile
    private var prefs: SharedPreferences? = null

    private fun prefs(context: Context): SharedPreferences {
        // Double-checked locking. A cold start deliberately drives two threads to
        // this method at once: AvelRenApp.start() on Dispatchers.IO and MainActivity
        // on the main thread. Concurrent creation of
        // EncryptedSharedPreferences/MasterKey for one file is a known cause of
        // crashes (KeyStoreException) and keyset corruption with irreversible loss
        // of the device credentials (audit H-4).
        prefs?.let { return it }
        return synchronized(this) {
            prefs ?: run {
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
        }
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
     * Clear the stored pair. We call this when the server returned a 401 on
     * guaranteed-ours headers — the installation no longer exists (for example, a
     * DB restore rolled back the registration). The next start will create a new one.
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

    /** Whether the one-time legacy migration of the permission history is already done (AND-2 B2). */
    fun notificationLegacyMigrated(context: Context): Boolean =
        prefs(context).getBoolean(KEY_NOTIF_MIGRATED, false)

    fun markNotificationLegacyMigrated(context: Context) {
        prefs(context).edit().putBoolean(KEY_NOTIF_MIGRATED, true).apply()
    }

    /** #117: whether the background-delivery hint was dismissed by the user. */
    fun backgroundHintDismissed(context: Context): Boolean =
        prefs(context).getBoolean(KEY_BG_HINT_DISMISSED, false)

    fun markBackgroundHintDismissed(context: Context) {
        prefs(context).edit().putBoolean(KEY_BG_HINT_DISMISSED, true).apply()
    }

    fun selectedCheckpoint(context: Context): Int =
        prefs(context).getInt(KEY_SELECTED, -1)

    fun saveSelectedCheckpoint(context: Context, id: Int) {
        prefs(context).edit().putInt(KEY_SELECTED, id).apply()
    }

    fun pendingFcmToken(context: Context): String? =
        prefs(context).getString(KEY_PENDING_FCM_TOKEN, null)

    /** Synchronous disk handoff: callers must not start enqueue/network when this returns false. */
    fun savePendingFcmToken(context: Context, token: String): Boolean =
        prefs(context).edit().putString(KEY_PENDING_FCM_TOKEN, token).commit()

    fun clearPendingFcmTokenIfMatches(context: Context, expected: String): Boolean {
        val p = prefs(context)
        if (p.getString(KEY_PENDING_FCM_TOKEN, null) != expected) return false
        return p.edit().remove(KEY_PENDING_FCM_TOKEN).commit()
    }
}
