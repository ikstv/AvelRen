package ua.avelren.app.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import ua.avelren.app.AvelRenApp
import ua.avelren.app.data.Api
import ua.avelren.app.data.Timeouts

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

        // Локальне сповіщення вже погашено. Серверний ACK — через repository
        // (централізований 401-recovery). Якщо немає installation або запит
        // не пройде, сервер повторить пуш — нічого не губиться.
        val app = context.applicationContext as? AvelRenApp ?: return
        val pending = goAsync()
        app.launchInScope {
            try {
                withinAckReceiverBudget {
                    app.installation.authenticatedCall { creds -> Api.ack(creds, alertId, kind) }
                }
                Log.i(TAG, "підтверджено алерт $alertId")
            } catch (e: TimeoutCancellationException) {
                Log.w(TAG, "ACK budget exceeded for alert $alertId")
            } catch (e: CancellationException) {
                throw e
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

internal suspend fun <T> withinAckReceiverBudget(
    timeoutMs: Long = Timeouts.ACK_RECEIVER_BUDGET_MS,
    block: suspend () -> T,
): T = withTimeout(timeoutMs) { block() }
