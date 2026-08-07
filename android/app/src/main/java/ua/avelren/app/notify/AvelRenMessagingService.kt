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
        val kind = data["type"] ?: "threshold"
        val title = data["title"] ?: "AvelRen"
        val body = data["body"] ?: ""

        // Health — інформація, а не алерт із підтвердженням: без ongoing,
        // без кнопки ОК, змахується як звичайне сповіщення.
        if (kind == "health") {
            Log.i(TAG, "отримано health-повідомлення")
            Notifications.showInfo(applicationContext, title, body)
            return
        }

        val alertId = data["alert_id"]?.toLongOrNull() ?: return
        Log.i(TAG, "отримано $kind-алерт $alertId")
        Notifications.show(applicationContext, alertId, kind, title, body)
    }

    override fun onNewToken(token: String) {
        // Токен змінюється при перевстановленні й очищенні даних. Не оновимо —
        // сповіщення мовчки перестануть приходити.
        val ctx = applicationContext
        val existing = DeviceStore.credentials(ctx)
        CoroutineScope(Dispatchers.IO).launch {
            try {
                if (existing == null) {
                    val creds = Api.registerDevice(token)
                    DeviceStore.saveCredentials(ctx, creds)
                } else {
                    Api.updateToken(existing, token)
                }
                Log.i(TAG, "токен оновлено")
            } catch (e: Exception) {
                // Дзеркало recovery в AvelRenApp: після DB restore updateToken
                // повертає 401, і без очищення credentials наступні push теж
                // ніколи не доставилися б (NEW-AUTH-2).
                if (existing != null && Api.isStaleInstallation(e)) {
                    Log.w(TAG, "installation мертва (401), створюю нову для нового токена")
                    DeviceStore.clearCredentials(ctx)
                    try {
                        val creds = Api.registerDevice(token)
                        DeviceStore.saveCredentials(ctx, creds)
                    } catch (retry: Exception) {
                        Log.w(TAG, "перереєстрація не вдалася: ${retry.message}")
                    }
                } else {
                    Log.w(TAG, "не вдалося оновити токен: ${e.message}")
                }
            }
        }
    }

    companion object {
        private const val TAG = "AvelRen/FCM"
    }
}
