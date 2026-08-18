package ua.avelren.app.notify

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import ua.avelren.app.AvelRenApp

/**
 * Receives pushes from the server.
 *
 * The server sends data messages, not notifications. This is intentional: a
 * notification is drawn by the system itself, and the app cannot make it
 * non-dismissible. We build the notification ourselves — with an "OK" button and
 * with no way to swipe it away.
 */
class AvelRenMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val type = data["type"] ?: "threshold"

        // Cancel — the server closed the alert (the queue dropped / the ETA passed /
        // the subscription was deleted). We dismiss the shown ongoing notification
        // (audit A-02). `kind` here is the alert type (threshold|eta), from which the
        // same notification id is computed as at show time.
        if (type == "cancel") {
            // The id is in cancel_alert_id, not alert_id: this way an old APK
            // (baseline c7d2e1f) shows nothing on this message (audit A-02 / B1).
            // The new one reads its own field.
            val kind = data["kind"] ?: return
            val alertId = data["cancel_alert_id"]?.toLongOrNull() ?: return
            Log.i(TAG, "отримано cancel $kind:$alertId")
            Notifications.cancel(applicationContext, kind, alertId)
            return
        }

        val title = data["title"] ?: "AvelRen"
        val body = data["body"] ?: ""

        // Health — information, not an alert with acknowledgement: no ongoing,
        // no OK button, dismissible like an ordinary notification.
        if (type == "health") {
            Log.i(TAG, "отримано health-повідомлення")
            Notifications.showInfo(applicationContext, title, body)
            return
        }

        val alertId = data["alert_id"]?.toLongOrNull() ?: return
        Log.i(TAG, "отримано $type-алерт $alertId")
        Notifications.show(applicationContext, alertId, type, title, body)
    }

    override fun onNewToken(token: String) {
        // The token changes on reinstall and data clear. If we do not update it,
        // notifications will silently stop arriving. No own register/recovery
        // logic: we delegate to the centralized repository (AND-1) — otherwise two
        // sources of 401 recovery diverge.
        Log.i(TAG, "новий FCM-токен, делегую repository")
        (applicationContext as? AvelRenApp)?.handleNewFcmToken(token)
    }

    companion object {
        private const val TAG = "AvelRen/FCM"
    }
}
