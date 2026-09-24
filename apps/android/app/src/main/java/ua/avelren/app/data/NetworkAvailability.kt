package ua.avelren.app.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import android.os.SystemClock
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged

object NetworkAvailability {
    // A radio signal measurement, not an inference from a slow server response.
    // Unknown/redacted values and cellular bearer-specific units are not guessed.
    internal fun weakWifiSignal(isWifi: Boolean, dbm: Int?): Boolean =
        isWifi && dbm != null && dbm in -126..-85

    private fun state(caps: NetworkCapabilities?): InternetState = when {
        caps == null -> InternetState.UNKNOWN
        caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) -> {
            val dbm = if (Build.VERSION.SDK_INT >= 29) caps.signalStrength else null
            if (weakWifiSignal(caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI), dbm))
                InternetState.WEAK else InternetState.ONLINE
        }
        else -> InternetState.OFFLINE
    }

    fun current(context: Context): InternetState = runCatching {
        val manager = context.getSystemService(ConnectivityManager::class.java)
            ?: return@runCatching InternetState.UNKNOWN
        val network = manager.activeNetwork ?: return@runCatching InternetState.OFFLINE
        state(manager.getNetworkCapabilities(network))
    }.getOrDefault(InternetState.UNKNOWN)

    fun states(context: Context): Flow<InternetState> = callbackFlow {
        val manager = context.getSystemService(ConnectivityManager::class.java)
        if (manager == null) {
            trySend(InternetState.UNKNOWN)
            close()
            return@callbackFlow
        }
        val stability = ConnectionStability()
        var settle: Job? = null
        fun publish(raw: InternetState) {
            val resolved = stability.observe(raw, SystemClock.elapsedRealtime())
            trySend(resolved)
            settle?.cancel()
            if (resolved == InternetState.WEAK && raw == InternetState.ONLINE) {
                settle = launch {
                    delay(60_000L)
                    trySend(stability.observe(current(context), SystemClock.elapsedRealtime()))
                }
            }
        }
        publish(current(context))
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                publish(InternetState.UNKNOWN)
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                publish(state(caps))
            }

            override fun onLost(network: Network) {
                // Losing the old default during handover is not necessarily
                // losing internet on the new default network.
                publish(current(context))
            }
        }
        // Слухаємо саме мережу запитів застосунку, не довільний Wi-Fi поряд.
        val registered = runCatching { manager.registerDefaultNetworkCallback(callback) }.isSuccess
        if (!registered) {
            trySend(InternetState.UNKNOWN)
            close()
            return@callbackFlow
        }
        awaitClose {
            settle?.cancel()
            runCatching { manager.unregisterNetworkCallback(callback) }
        }
    }.conflate().distinctUntilChanged()
}
