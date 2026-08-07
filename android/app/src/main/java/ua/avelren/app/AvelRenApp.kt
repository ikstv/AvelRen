package ua.avelren.app

import android.app.Application
import android.util.Log
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.notify.Notifications

class AvelRenApp : Application() {

    override fun onCreate() {
        super.onCreate()

        // Канал створюємо одразу: якщо його не буде на момент першого пуша,
        // сповіщення просто не з'явиться.
        Notifications.ensureChannel(this)

        CoroutineScope(Dispatchers.IO).launch { registerOrRecover() }
    }

    /**
     * Реєстрація або відновлення після DB restore.
     *
     * Раніше updateToken() при 401 навіть не кидав exception (Ktor без
     * expectSuccess), тож клієнт лишався з мертвою парою назавжди
     * (NEW-AUTH-2). Тепер Ktor кидає ClientRequestException на 4xx; при 401
     * ми свідомо викидаємо стару installation і створюємо нову — саме той
     * recovery-flow, який DeviceStore.clearCredentials обіцяє в docstring.
     *
     * `FirebaseMessaging.token.await()` теж під `try`: без цього одна помилка
     * Google Play services (offline при холодному старті, застаріла версія
     * сервісів, чорний тайм-аут) роняла весь launch-корутина без жодного
     * логу — і повторної спроби вже не було до перезапуску процесу.
     */
    private suspend fun registerOrRecover() {
        val existing = DeviceStore.credentials(this)
        val token = try {
            FirebaseMessaging.getInstance().token.await()
        } catch (e: Exception) {
            Log.w(TAG, "не вдалося отримати FCM-токен: ${e.message}")
            return
        }
        try {
            if (existing == null) {
                val creds = Api.registerDevice(token)
                DeviceStore.saveCredentials(this, creds)
                Log.i(TAG, "пристрій зареєстровано")
            } else {
                Api.updateToken(existing, token)
            }
        } catch (e: Exception) {
            if (existing != null && Api.isStaleInstallation(e)) {
                Log.w(TAG, "installation мертва (401), створюю нову")
                DeviceStore.clearCredentials(this)
                try {
                    val creds = Api.registerDevice(token)
                    DeviceStore.saveCredentials(this, creds)
                    Log.i(TAG, "пристрій перереєстровано")
                } catch (retry: Exception) {
                    Log.w(TAG, "перереєстрація не вдалася: ${retry.message}")
                }
            } else {
                Log.w(TAG, "реєстрація не вдалася: ${e.message}")
            }
        }
    }

    companion object {
        private const val TAG = "AvelRen"
    }
}
