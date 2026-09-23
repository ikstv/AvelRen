package ua.avelren.app.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged

object NetworkAvailability {
    private fun state(caps: NetworkCapabilities?): InternetState = when {
        caps == null -> InternetState.UNKNOWN
        caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) -> InternetState.ONLINE
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
        trySend(current(context))
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                trySend(InternetState.UNKNOWN)
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                trySend(state(caps))
            }

            override fun onLost(network: Network) {
                trySend(InternetState.OFFLINE)
            }
        }
        // Слухаємо саме мережу запитів застосунку, не довільний Wi-Fi поряд.
        val registered = runCatching { manager.registerDefaultNetworkCallback(callback) }.isSuccess
        if (!registered) {
            trySend(InternetState.UNKNOWN)
            close()
            return@callbackFlow
        }
        awaitClose { runCatching { manager.unregisterNetworkCallback(callback) } }
    }.conflate().distinctUntilChanged()
}
