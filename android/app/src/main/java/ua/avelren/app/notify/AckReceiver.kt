package ua.avelren.app.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore

/**
 * Кнопка «ОК» зі шторки.
 *
 * Сповіщення гасимо одразу, не чекаючи на відповідь сервера: користувач
 * натиснув — воно має зникнути негайно, інакше здається зламаним. Якщо запит
 * не пройде, сервер надішле пуш ще раз через п'ять хвилин, і нічого не
 * загубиться. Повторне підтвердження сервер сприймає спокійно.
 */
class AckReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val alertId = intent.getLongExtra(EXTRA_ALERT_ID, -1L)
        val kind = intent.getStringExtra(EXTRA_KIND) ?: "threshold"
        if (alertId <= 0) return

        Notifications.cancel(context, kind, alertId)

        val deviceId = DeviceStore.deviceId(context) ?: return
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                Api.ack(deviceId, alertId, kind)
                Log.i(TAG, "підтверджено алерт $alertId")
            } catch (e: Exception) {
                Log.w(TAG, "не вдалося підтвердити $alertId, сервер повторить: ${e.message}")
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val EXTRA_ALERT_ID = "alert_id"
        const val EXTRA_KIND = "kind"
        private const val TAG = "AvelRen/Ack"
    }
}
