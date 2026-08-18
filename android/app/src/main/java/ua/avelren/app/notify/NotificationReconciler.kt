package ua.avelren.app.notify

import android.app.NotificationManager
import android.content.Context
import android.util.Log
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import ua.avelren.app.data.Api
import ua.avelren.app.data.InstallationRepository
import ua.avelren.app.data.InstallationState

/**
 * The second layer of A-02: brings shown notifications in line with the
 * canonical server state.
 *
 * The cancel-push is the fast path, but it can be lost (Doze, offline, a
 * force-stop right at the moment of expiry). So on every return of the app to the
 * foreground (and after a successful registration) we reconcile the shown ongoing
 * notifications against `GET /active-alerts` and dismiss those the server no
 * longer considers active.
 *
 * FAIL-SAFE (a mandatory invariant): we touch local notifications ONLY after a
 * successful 200 response. Any error (offline, 5xx, 401 before recovery
 * completes, missing credentials) — we dismiss nothing. Otherwise a network
 * failure would look like "the server says: there are none active" and the app
 * would dismiss all the real alarms itself.
 */
object NotificationReconciler {

    private const val TAG = "AvelRen/Reconcile"

    // Reconcile is idempotent, but the foreground event and the completion of
    // registration can arrive almost simultaneously — the Mutex keeps them from running in parallel.
    private val mutex = Mutex()

    suspend fun reconcile(context: Context, installation: InstallationRepository) {
        // Not ready yet (no installation) — nothing to reconcile. We do not force
        // registration for the sake of reconciliation: this is a best-effort layer.
        if (installation.state.value !is InstallationState.Ready) return

        mutex.withLock {
            val nm = context.getSystemService(NotificationManager::class.java) ?: return

            // 1. A snapshot of local notifications BEFORE the request to the server.
            //    This closes a race (audit A-02 / B2): if a new valid alert arrives
            //    AFTER the server built its response, it will not be in this
            //    snapshot, so reconciliation will not dismiss it. We dismiss only
            //    what was shown at the moment before the request.
            val snapshot = nm.activeNotifications.map { sbn ->
                ActiveNotification(sbn.id, keyFromExtras(sbn.notification.extras))
            }

            // 2. Only now do we ask the server — through the repository, so a 401
            //    (DB restore) is recovered and retried centrally. Any failed result
            //    → serverKeys=null (fail-safe below).
            val serverKeys: Set<AlertKey>? = try {
                val server = installation.authenticatedCall { creds -> Api.activeAlerts(creds) }
                buildSet {
                    server.threshold.forEach { add(AlertKey("threshold", it)) }
                    server.eta.forEach { add(AlertKey("eta", it)) }
                }
            } catch (e: Exception) {
                Log.w(TAG, "не вдалося отримати active-alerts, лишаю все як є: ${e.message}")
                null
            }

            // 3. FAIL-SAFE: serverKeys==null (fetch/recovery failed) → we dismiss
            //    nothing. Diff the snapshot (not a fresh read) against the server state.
            val stale = AlertReconciliation.staleNotificationIdsOrNothing(snapshot, serverKeys)
            for (id in stale) {
                nm.cancel(id)
                Log.i(TAG, "погашено застаріле сповіщення id=$id")
            }
        }
    }

    /** The full key from the notification's extras, or null (an old/foreign notification). */
    private fun keyFromExtras(extras: android.os.Bundle?): AlertKey? {
        if (extras == null) return null
        val kind = extras.getString(Notifications.EXTRA_KIND) ?: return null
        if (!extras.containsKey(Notifications.EXTRA_ALERT_ID)) return null
        return AlertKey(kind, extras.getLong(Notifications.EXTRA_ALERT_ID))
    }
}
