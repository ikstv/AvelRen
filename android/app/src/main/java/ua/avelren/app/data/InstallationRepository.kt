package ua.avelren.app.data

import android.util.Log
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class InstallationRepository(
    private val api: InstallationApi,
    private val store: CredentialStore,
    private val tokens: FcmTokenProvider,
    private val scope: CoroutineScope,
    private val pendingTokens: PendingFcmTokenStore = InMemoryPendingFcmTokenStore(),
    private val retryScheduler: FcmTokenRetryScheduler = ImmediateFcmTokenRetryScheduler(),
    // Інжектований, як і решта залежностей вище: android.util.Log — платформний
    // стаб, у plain JUnit кидає "not mocked". Продакшн отримує реальний Log.w
    // за замовчуванням; тести підміняють no-op, не чіпаючи глобальний
    // testOptions (див. коментар у InstallationRepositoryTest.kt).
    private val logUnavailable: (String, Throwable?) -> Unit =
        { msg, cause -> Log.w("Installation", msg, cause) },
) {
    private val _state = MutableStateFlow<InstallationState>(InstallationState.Initializing)
    val state: StateFlow<InstallationState> = _state.asStateFlow()
    private val mutex = Mutex()
    private val pendingTokenMutex = Mutex()
    private val tokenSyncMutex = Mutex()
    @Volatile private var creds: DeviceStore.Credentials? = null

    fun start() { scope.launch { initialize() } }

    internal suspend fun initialize() {
        mutex.withLock {
            store.load()?.also { creds = it; _state.value = InstallationState.Ready(it.deviceId) }
        }
        resumePendingTokenSync()
        val tokenResult = runCatching { tokens.currentToken() }
        val token = tokenResult.getOrNull()
        if (token != null) onNewFcmToken(token)
        else if (mutex.withLock { creds ?: store.load() } == null &&
            pendingTokenMutex.withLock { pendingTokens.load() } == null) {
            // Аудит 2026-08-15: цей виняток раніше ковтався мовчки
            // (.getOrNull()), і саме тому потрібен був тимчасовий Log.e,
            // щоб дістати справжню причину (невалідний google-services.json
            // → FirebaseMessaging.getToken() кидав IllegalArgumentException
            // ще до мережі). Reason тепер несе повідомлення винятку, а не
            // узагальнений текст; Log.w — постійний, щоб наступного разу
            // причина була видна з першого logcat, без тимчасової правки коду.
            val cause = tokenResult.exceptionOrNull()
            val reason = cause?.message ?: "немає FCM-токена для реєстрації"
            logUnavailable("FCM-токен недоступний: installation Unavailable", cause)
            _state.value = InstallationState.Unavailable(reason)
        }
    }

    suspend fun onNewFcmToken(token: String) {
        if (!pendingTokenMutex.withLock { pendingTokens.save(token) }) return
        if (retryScheduler.enqueue() is ScheduleResult.Enqueued) syncPendingTokenOnce()
    }

    internal suspend fun resumePendingTokenSync(): PendingTokenSyncOutcome {
        if (pendingTokenMutex.withLock { pendingTokens.load() } == null) return PendingTokenSyncOutcome.NothingPending
        return when (val result = retryScheduler.enqueue()) {
            is ScheduleResult.Enqueued -> syncPendingTokenOnce()
            is ScheduleResult.Failed -> PendingTokenSyncOutcome.RetryableFailure(result.cause)
        }
    }

    internal suspend fun syncPendingTokenOnce(): PendingTokenSyncOutcome = tokenSyncMutex.withLock {
        val token = pendingTokenMutex.withLock { pendingTokens.load() }
            ?: return@withLock PendingTokenSyncOutcome.NothingPending
        try {
            syncToken(token)
            pendingTokenMutex.withLock { pendingTokens.clearIfMatches(token) }
            PendingTokenSyncOutcome.Synced
        } catch (e: CancellationException) { throw e }
        catch (e: Throwable) { classifyTokenSyncFailure(e) }
    }

    private suspend fun syncToken(token: String) {
        val current = mutex.withLock { creds ?: store.load()?.also { creds = it } }
        if (current == null) {
            mutex.withLock {
                val latest = creds ?: store.load()?.also { creds = it }
                if (latest == null) registerFreshLocked(token)
                else updateFreshTokenLocked(latest, token)
            }
            return
        }
        try {
            api.updateToken(current, token)
        } catch (e: Throwable) {
            if (!api.isStaleInstallation(e)) throw e
            mutex.withLock {
                // The register-vs-existing decision is atomic. If another operation recovered
                // while the first PUT was in flight, synchronize X on that fresh pair instead.
                val latest = creds
                if (latest != null && latest != current) updateFreshTokenLocked(latest, token)
                else try { registerFreshLocked(token) }
                catch (recoveryError: Throwable) {
                    invalidateLocked("перереєстрація не вдалась: ${recoveryError.message}")
                    throw recoveryError
                }
            }
        }
    }

    private suspend fun updateFreshTokenLocked(fresh: DeviceStore.Credentials, token: String) {
        try {
            api.updateToken(fresh, token)
        } catch (e: Throwable) {
            if (api.isStaleInstallation(e)) {
                invalidateIfLocked(fresh, "сервер відкинув щойно зареєстровану installation")
            }
            throw e
        }
    }

    suspend fun <T> authenticatedCall(block: suspend (DeviceStore.Credentials) -> T): T {
        val first = currentOrRegister() ?: error("installation недоступна")
        try { return block(first) } catch (e: Throwable) {
            if (!api.isStaleInstallation(e)) throw e
        }
        recoverFrom(first)
        val fresh = creds ?: error("installation недоступна після recovery")
        try { return block(fresh) } catch (e: Throwable) {
            if (api.isStaleInstallation(e)) invalidateIf(fresh, "сервер відкинув щойно зареєстровану installation")
            throw e
        }
    }

    private suspend fun currentOrRegister(): DeviceStore.Credentials? {
        creds?.let { return it }
        return mutex.withLock {
            creds ?: runCatching { registerFreshLocked(tokens.currentToken()); creds }.getOrNull()
        }
    }

    private suspend fun recoverFrom(stale: DeviceStore.Credentials) = mutex.withLock {
        if (creds != stale) return@withLock
        try { registerFreshLocked(tokens.currentToken()) }
        catch (e: Throwable) { invalidateLocked("recovery не вдалась: ${e.message}"); throw e }
    }

    private fun invalidateLocked(reason: String) { store.clear(); creds = null; _state.value = InstallationState.Unavailable(reason) }
    private fun invalidateIfLocked(used: DeviceStore.Credentials, reason: String) {
        if (creds == used) invalidateLocked(reason)
    }
    private suspend fun invalidateIf(used: DeviceStore.Credentials, reason: String) = mutex.withLock { if (creds == used) invalidateLocked(reason) }

    private suspend fun registerFreshLocked(token: String) {
        store.clear(); val fresh = api.registerDevice(token); store.save(fresh); creds = fresh
        _state.value = InstallationState.Ready(fresh.deviceId)
    }
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
}
interface CredentialStore { fun load(): DeviceStore.Credentials?; fun save(creds: DeviceStore.Credentials); fun clear() }
interface FcmTokenProvider { suspend fun currentToken(): String }

object ProtectedLoad {
    suspend fun observe(
        state: StateFlow<InstallationState>,
        onReady: suspend (InstallationState.Ready) -> Unit,
    ) = state.filterIsInstance<InstallationState.Ready>().distinctUntilChanged()
        .collect { onReady(it) }
}
