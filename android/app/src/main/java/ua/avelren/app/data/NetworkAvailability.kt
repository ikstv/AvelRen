package ua.avelren.app.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate

/**
 * Сигнал «стан зв'язку змінився» — і поява, і втрата мережі.
 *
 * Автооновлення живе на 60-секундному циклі (`LiveRefresh.INTERVAL_MS`), і це
 * правильний період — збирач на сервері теж працює раз на хвилину, частіше
 * питати нема сенсу. Але коли інтернет пропав чи повернувся, чекати повний
 * цикл — надто довго в обидва боки: при відновленні екран лишається з червоною
 * плашкою, при втраті — навпаки показує «онлайн», якого вже нема. Тут ми
 * дізнаємось про зміну від системи й оновлюємось одразу.
 *
 * `onAvailable` дає негайний refresh (успіх → плашка зеленіє), `onLost` — теж
 * refresh, але запит миттєво падає без мережі й плашка червоніє відразу, а не
 * через хвилину.
 *
 * `onAvailable` спрацьовує і в момент реєстрації, якщо мережа вже є — тобто на
 * старті екрана прилетить один сигнал понад той refresh, що робить сам цикл.
 * Це свідомо не фільтрується: пропустити реальну зміну гірше, ніж зробити один
 * зайвий запит, а `conflate` гасить чергу, коли система шле кілька подій
 * поспіль (Wi-Fi + мобільна мережа перемкнулись разом).
 */
object NetworkAvailability {

    fun events(ctx: Context): Flow<Unit> = callbackFlow {
        val manager = ctx.getSystemService(ConnectivityManager::class.java)
        if (manager == null) {
            // Сервіс недоступний — лишаємось на 60-секундному циклі, а не падаємо.
            close()
            return@callbackFlow
        }

        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                trySend(Unit)
            }

            // Мережа зникла — не чекаємо повний цикл із застряглим «онлайн»:
            // штовхаємо refresh, він упаде без зв'язку і плашка почервоніє.
            override fun onLost(network: Network) {
                trySend(Unit)
            }
        }

        val request = NetworkRequest.Builder()
            // NET_CAPABILITY_INTERNET, а не просто «є мережа»: підключення до
            // Wi-Fi без виходу в інтернет (captive portal, роутер без аплінку)
            // не повинно тригерити запит, який усе одно провалиться.
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()

        runCatching { manager.registerNetworkCallback(request, callback) }
            .onFailure { close(it) }

        awaitClose {
            runCatching { manager.unregisterNetworkCallback(callback) }
        }
    }.conflate()
}
