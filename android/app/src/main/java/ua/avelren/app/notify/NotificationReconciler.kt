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
 * Другий шар A-02: приводить показані сповіщення до canonical server-стану.
 *
 * cancel-push — швидкий шлях, але він може загубитися (Doze, offline,
 * force-stop саме в момент expire). Тому при кожному поверненні застосунку у
 * foreground (і після успішної реєстрації) звіряємо показані ongoing-
 * сповіщення з `GET /active-alerts` і гасимо ті, яких сервер уже не вважає
 * активними.
 *
 * FAIL-SAFE (обов'язковий інваріант): локальні сповіщення чіпаємо ЛИШЕ після
 * успішної 200-відповіді. Будь-яка помилка (offline, 5xx, 401 до завершення
 * recovery, відсутні credentials) — нічого не гасимо. Інакше мережевий збій
 * виглядав би як «сервер каже: активних нема» і застосунок сам погасив би всі
 * справжні тривоги.
 */
object NotificationReconciler {

    private const val TAG = "AvelRen/Reconcile"

    // Reconcile ідемпотентний, але foreground-подія і завершення реєстрації
    // можуть настати майже одночасно — Mutex не дає їм бігти паралельно.
    private val mutex = Mutex()

    suspend fun reconcile(context: Context, installation: InstallationRepository) {
        // Ще не готові (немає installation) — нема що звіряти. Не форсуємо
        // реєстрацію заради reconciliation: це best-effort шар.
        if (installation.state.value !is InstallationState.Ready) return

        mutex.withLock {
            val nm = context.getSystemService(NotificationManager::class.java) ?: return

            // 1. Знімок локальних сповіщень ДО запиту до сервера. Це закриває
            //    race (аудит A-02 / B2): якщо новий валідний alert прийде вже
            //    ПІСЛЯ того, як сервер сформував відповідь, він не буде в
            //    цьому знімку, тож reconciliation його не погасить. Гасимо
            //    лише те, що показувалось на момент до запиту.
            val snapshot = nm.activeNotifications.map { sbn ->
                ActiveNotification(sbn.id, keyFromExtras(sbn.notification.extras))
            }

            // 2. Лише тепер питаємо сервер — через repository, тож 401 (DB
            //    restore) централізовано відновлюється й ретраїться. Будь-який
            //    невдалий результат → serverKeys=null (fail-safe нижче).
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

            // 3. FAIL-SAFE: serverKeys==null (fetch/recovery впав) → не гасимо
            //    нічого. Diff саме знімка (не свіжого читання) проти server-стану.
            val stale = AlertReconciliation.staleNotificationIdsOrNothing(snapshot, serverKeys)
            for (id in stale) {
                nm.cancel(id)
                Log.i(TAG, "погашено застаріле сповіщення id=$id")
            }
        }
    }

    /** Повний ключ з extras сповіщення або null (старе/чуже сповіщення). */
    private fun keyFromExtras(extras: android.os.Bundle?): AlertKey? {
        if (extras == null) return null
        val kind = extras.getString(Notifications.EXTRA_KIND) ?: return null
        if (!extras.containsKey(Notifications.EXTRA_ALERT_ID)) return null
        return AlertKey(kind, extras.getLong(Notifications.EXTRA_ALERT_ID))
    }
}
