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

    data class Credentials(val deviceId: String, val deviceSecret: String) {
        override fun toString() = "Credentials([redacted])"
    }

    internal val preferencesLock = Any()
    private var acknowledgedPreferences: AcknowledgedRecoveryPreferences? = null

    internal fun recoveryPreferences(context: Context): RecoveryPreferences = synchronized(preferencesLock) {
        acknowledgedPreferences ?: AcknowledgedRecoveryPreferences(
            SharedRecoveryPreferences(prefs(context), preferencesLock),
        ).also { acknowledgedPreferences = it }
    }

    private fun editUnrelated(context: Context, edit: (SharedPreferences.Editor) -> Unit) {
        synchronized(preferencesLock) {
            recoveryPreferences(context)
            acknowledgedPreferences!!.editUnrelated {
                val editor = prefs(context).edit()
                edit(editor)
                editor.apply()
            }
        }
    }

    /** Publishes only a disk-acknowledged exact-pair replacement. */
    fun commitCredentialsIfMatches(context: Context, expected: Credentials?, replacement: Credentials?): Boolean =
        synchronized(preferencesLock) {
            DeviceRecoveryStore.commitCredentials(recoveryPreferences(context), expected, replacement)
        }

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
        return synchronized(preferencesLock) {
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

    fun credentials(context: Context): Credentials? = synchronized(preferencesLock) {
        DeviceRecoveryStore.credentials(recoveryPreferences(context))
    }

    fun saveCredentials(context: Context, creds: Credentials) {
        synchronized(preferencesLock) {
            commitCredentialsIfMatches(context, credentials(context), creds)
        }
    }

    /** Legacy caller; permission and onboarding history remain intact. */
    fun clearCredentials(context: Context) {
        synchronized(preferencesLock) {
            commitCredentialsIfMatches(context, credentials(context), null)
        }
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
        editUnrelated(context) { it.putBoolean(KEY_NOTIF_ASKED, h.asked)
            .putBoolean(KEY_NOTIF_DENIED, h.deniedOnce)
            .putBoolean(KEY_NOTIF_GRANTED, h.everGranted) }
    }

    /** Whether the one-time legacy migration of the permission history is already done (AND-2 B2). */
    fun notificationLegacyMigrated(context: Context): Boolean =
        prefs(context).getBoolean(KEY_NOTIF_MIGRATED, false)

    fun markNotificationLegacyMigrated(context: Context) {
        editUnrelated(context) { it.putBoolean(KEY_NOTIF_MIGRATED, true) }
    }

    /** #117: whether the background-delivery hint was dismissed by the user. */
    fun backgroundHintDismissed(context: Context): Boolean =
        prefs(context).getBoolean(KEY_BG_HINT_DISMISSED, false)

    fun markBackgroundHintDismissed(context: Context) {
        editUnrelated(context) { it.putBoolean(KEY_BG_HINT_DISMISSED, true) }
    }

    fun selectedCheckpoint(context: Context): Int =
        prefs(context).getInt(KEY_SELECTED, -1)

    fun saveSelectedCheckpoint(context: Context, id: Int) {
        editUnrelated(context) { it.putInt(KEY_SELECTED, id) }
    }

    fun pendingFcmToken(context: Context): String? = synchronized(preferencesLock) {
        recoveryPreferences(context).get(KEY_PENDING_FCM_TOKEN)
    }

    /** Synchronous disk handoff: callers must not start enqueue/network when false. */
    fun savePendingFcmToken(context: Context, token: String): Boolean = synchronized(preferencesLock) {
        recoveryPreferences(context).commit(mapOf(KEY_PENDING_FCM_TOKEN to token))
    }

    fun clearPendingFcmTokenIfMatches(context: Context, expected: String): Boolean = synchronized(preferencesLock) {
        val p = recoveryPreferences(context)
        if (p.get(KEY_PENDING_FCM_TOKEN) != expected) return@synchronized false
        p.commit(mapOf(KEY_PENDING_FCM_TOKEN to null))
    }
}
