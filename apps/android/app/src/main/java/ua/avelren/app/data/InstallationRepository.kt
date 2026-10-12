package ua.avelren.app.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch

/** All identity/token mutations share the durable coordinator, including worker and 401 recovery. */
class InstallationRepository(
    api: InstallationApi,
    store: CredentialStore,
    tokens: FcmTokenProvider,
    private val scope: CoroutineScope,
    recoveryStore: RecoveryStore,
    credentialCommitter: CredentialCommitter,
    retryScheduler: FcmTokenRetryScheduler = ImmediateFcmTokenRetryScheduler(),
) {
    private val coordinator = FcmRecoveryCoordinator(
        api = object : RecoveryApi {
            override suspend fun register(token: String) = api.registerDevice(token)
            override suspend fun update(creds: DeviceStore.Credentials, token: String) = api.updateToken(creds, token)
            override fun isStale(error: Throwable) = api.isStaleInstallation(error)
            override fun isTokenConflict(error: Throwable) = api.isTokenConflict(error)
        },
        credentials = store::load,
        committer = credentialCommitter,
        records = recoveryStore,
        tokens = tokens,
        scheduler = retryScheduler,
    )
    val state: StateFlow<InstallationState> = coordinator.state
    val pushState: StateFlow<PushSyncState> = coordinator.pushState

    fun start() { scope.launch { initialize() } }
    internal suspend fun initialize() = coordinator.initialize()

    // Firebase callbacks are signals. SDK readback wins over a delayed callback payload.
    @Suppress("UNUSED_PARAMETER")
    suspend fun onNewFcmToken(token: String) = coordinator.providerSignal()
    suspend fun retryBlocked() = coordinator.retryBlocked()
    internal suspend fun syncOnce(): PendingTokenSyncOutcome = coordinator.syncOnce()
    internal suspend fun syncPendingTokenOnce(): PendingTokenSyncOutcome = syncOnce()
    internal suspend fun resumePendingTokenSync(): PendingTokenSyncOutcome {
        initialize()
        return syncOnce()
    }
    suspend fun <T> authenticatedCall(block: suspend (DeviceStore.Credentials) -> T): T =
        coordinator.authenticatedCall(block)
}

sealed interface InstallationState {
    data object Initializing : InstallationState
    data class Ready(val deviceId: String) : InstallationState
    data class Unavailable(val reason: String) : InstallationState
}

interface InstallationApi {
    suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials
    suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String)
    fun isStaleInstallation(exc: Throwable): Boolean
    fun isTokenConflict(exc: Throwable): Boolean = exc is TokenConflictException
}
interface CredentialStore { fun load(): DeviceStore.Credentials?; fun save(creds: DeviceStore.Credentials); fun clear() }
interface FcmTokenProvider : RotatingTokenSource

object ProtectedLoad {
    suspend fun observe(
        state: StateFlow<InstallationState>,
        onReady: suspend (InstallationState.Ready) -> Unit,
    ) = state.filterIsInstance<InstallationState.Ready>().distinctUntilChanged()
        .collect { onReady(it) }
}
