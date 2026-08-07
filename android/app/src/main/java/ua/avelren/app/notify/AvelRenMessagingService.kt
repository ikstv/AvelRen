package ua.avelren.app.notify

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import ua.avelren.app.AvelRenApp

/**
 * Приймає пуші від сервера.
 *
 * Сервер шле data-повідомлення, а не notification. Це навмисно: notification
 * малює сама система, і застосунок не може зробити його незникаючим. Ми
 * будуємо сповіщення самі — з кнопкою «ОК» і без можливості змахнути.
 */
class AvelRenMessagingService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val data = message.data
        val type = data["type"] ?: "threshold"

        // Cancel — сервер закрив алерт (черга впала / ETA минув / підписку
        // видалено). Гасимо показане ongoing-сповіщення (аудит A-02). `kind`
        // тут — тип алерта (threshold|eta), з нього рахується той самий
        // notification id, що й при показі.
        if (type == "cancel") {
            // id саме в cancel_alert_id, не в alert_id: так старий APK
            // (baseline c7d2e1f) на цьому повідомленні нічого не показує
            // (аудит A-02 / B1). Новий читає власне поле.
            val kind = data["kind"] ?: return
            val alertId = data["cancel_alert_id"]?.toLongOrNull() ?: return
            Log.i(TAG, "отримано cancel $kind:$alertId")
            Notifications.cancel(applicationContext, kind, alertId)
            return
        }

        val title = data["title"] ?: "AvelRen"
        val body = data["body"] ?: ""

        // Health — інформація, а не алерт із підтвердженням: без ongoing,
        // без кнопки ОК, змахується як звичайне сповіщення.
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
        // Токен змінюється при перевстановленні й очищенні даних. Не оновимо —
        // сповіщення мовчки перестануть приходити. Жодної власної
        // register/recovery логіки: делегуємо централізованому repository
        // (AND-1) — інакше два джерела 401-recovery розходяться.
        Log.i(TAG, "новий FCM-токен, делегую repository")
        (applicationContext as? AvelRenApp)?.handleNewFcmToken(token)
    }

    companion object {
        private const val TAG = "AvelRen/FCM"
    }
}
