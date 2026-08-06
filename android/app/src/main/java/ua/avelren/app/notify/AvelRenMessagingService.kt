package ua.avelren.app.notify

import android.util.Log
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore

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
        val alertId = data["alert_id"]?.toLongOrNull() ?: return
        val kind = data["type"] ?: "threshold"
        val title = data["title"] ?: "AvelRen"
        val body = data["body"] ?: ""

        Log.i(TAG, "отримано $kind-алерт $alertId")
        Notifications.show(applicationContext, alertId, kind, title, body)
    }

    override fun onNewToken(token: String) {
        // Токен змінюється при перевстановленні й очищенні даних. Не оновимо —
        // сповіщення мовчки перестануть приходити.
        val deviceId = DeviceStore.deviceId(applicationContext)
        CoroutineScope(Dispatchers.IO).launch {
            try {
                if (deviceId == null) {
                    val id = Api.registerDevice(token)
                    DeviceStore.saveDeviceId(applicationContext, id)
                } else {
                    Api.updateToken(deviceId, token)
                }
                Log.i(TAG, "токен оновлено")
            } catch (e: Exception) {
                Log.w(TAG, "не вдалося оновити токен: ${e.message}")
            }
        }
    }

    companion object {
        private const val TAG = "AvelRen/FCM"
    }
}
