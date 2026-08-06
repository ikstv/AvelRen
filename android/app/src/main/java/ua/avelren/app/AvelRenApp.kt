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

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val token = FirebaseMessaging.getInstance().token.await()
                val existing = DeviceStore.deviceId(this@AvelRenApp)
                if (existing == null) {
                    val id = Api.registerDevice(token)
                    DeviceStore.saveDeviceId(this@AvelRenApp, id)
                    Log.i(TAG, "пристрій зареєстровано")
                } else {
                    Api.updateToken(existing, token)
                }
            } catch (e: Exception) {
                Log.w(TAG, "реєстрація не вдалася: ${e.message}")
            }
        }
    }

    companion object {
        private const val TAG = "AvelRen"
    }
}
