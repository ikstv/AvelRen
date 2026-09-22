package ua.avelren.app.data

import androidx.work.ListenableWorker
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.yield
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FcmTokenRetryTest {
    private class Stale : RuntimeException()
    private open class Api : InstallationApi {
        var registrations = 0
        var updates = 0
        val updated = mutableListOf<String>()
        override suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials {
            yield(); registrations++
            return DeviceStore.Credentials("device-$registrations", "secret-$registrations")
        }
        override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) { updates++; updated += fcmToken }
        override fun isStaleInstallation(exc: Throwable) = exc is Stale
    }
    private class Store(seed: DeviceStore.Credentials? = null) : CredentialStore {
        var value = seed
        override fun load() = value
        override fun save(creds: DeviceStore.Credentials) { value = creds }
        override fun clear() { value = null }
    }
    @Test fun `worker retries when repository is unavailable`() = runTest {
        val result = runFcmTokenSync(null)
        assertEquals(ListenableWorker.Result.Retry::class, result::class)
    }

    @Test fun `enqueue failure preserves pending token and makes no HTTP call`() = runTest {
        val pending = InMemoryPendingFcmTokenStore()
        val scheduler = object : FcmTokenRetryScheduler {
            override suspend fun enqueue() = ScheduleResult.Failed(IOException("offline scheduler"))
        }
        var updates = 0
        val repository = InstallationRepository(
            api = object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String) = error("HTTP must not run")
                override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) { updates++ }
                override fun isStaleInstallation(exc: Throwable) = false
            },
            store = object : CredentialStore {
                override fun load() = null
                override fun save(creds: DeviceStore.Credentials) = error("unused")
                override fun clear() = error("unused")
            },
            tokens = object : FcmTokenProvider { override suspend fun currentToken() = "unused" },
            scope = CoroutineScope(Dispatchers.Unconfined),
            pendingTokens = pending,
            retryScheduler = scheduler,
        )

        repository.onNewFcmToken("token-X")

        assertEquals("token-X", pending.load())
        assertEquals(0, updates)
    }

    @Test fun `save failure does not enqueue or call HTTP`() = runTest {
        var enqueues = 0
        val pending = object : PendingFcmTokenStore {
            override fun load() = null
            override fun save(token: String) = false
            override fun clearIfMatches(expectedToken: String) = error("unused")
        }
        val scheduler = object : FcmTokenRetryScheduler {
            override suspend fun enqueue(): ScheduleResult { enqueues++; return ScheduleResult.Enqueued }
        }
        val repository = InstallationRepository(
            api = object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String) = error("HTTP must not run")
                override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = error("HTTP must not run")
                override fun isStaleInstallation(exc: Throwable) = false
            },
            store = object : CredentialStore {
                override fun load() = null
                override fun save(creds: DeviceStore.Credentials) = Unit
                override fun clear() = Unit
            },
            tokens = object : FcmTokenProvider { override suspend fun currentToken() = "unused" },
            scope = CoroutineScope(Dispatchers.Unconfined),
            pendingTokens = pending,
            retryScheduler = scheduler,
        )

        repository.onNewFcmToken("token-X")

        assertEquals(0, enqueues)
    }

    @Test fun `failure classification is retryable for transport errors`() {
        assertTrue(classifyTokenSyncFailure(IOException("timeout")) is PendingTokenSyncOutcome.RetryableFailure)
    }

    @Test fun `credential registration race synchronizes pending token before clear`() = runTest {
        val api = Api()
        val pending = InMemoryPendingFcmTokenStore().also { it.save("token-X") }
        val repository = InstallationRepository(api, Store(),
            object : FcmTokenProvider { override suspend fun currentToken() = "token-Y" },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())
        val registration = async { repository.authenticatedCall { "registered" } }
        yield()
        repository.syncPendingTokenOnce()
        registration.await()
        assertTrue(api.updated.contains("token-X"))
        assertEquals(null, pending.load())
    }

    @Test fun `self 401 recovery registers token without redundant PUT`() = runTest {
        val api = object : Api() {
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) { throw Stale() }
        }
        val store = Store(DeviceStore.Credentials("old", "secret"))
        val pending = InMemoryPendingFcmTokenStore()
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider { override suspend fun currentToken() = "unused" },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())
        repository.onNewFcmToken("token-X")
        assertEquals(null, pending.load())
        assertEquals(DeviceStore.Credentials("device-1", "secret-1"), store.value)
        assertEquals(1, api.registrations)
    }

    @Test fun `successful pending startup recovery stays Ready when Firebase token fails`() = runTest {
        val api = Api()
        val store = Store()
        val pending = InMemoryPendingFcmTokenStore().also { it.save("token-X") }
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider { override suspend fun currentToken() = error("Firebase unavailable") },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())

        repository.initialize()

        assertTrue(repository.state.value is InstallationState.Ready)
        assertEquals(null, pending.load())
        assertEquals(DeviceStore.Credentials("device-1", "secret-1"), store.value)
    }

    @Test fun `persisted credential load is serialized with pending sync`() = runTest {
        val api = Api()
        val store = Store(DeviceStore.Credentials("old", "secret"))
        val pending = InMemoryPendingFcmTokenStore().also { it.save("token-X") }
        val repository = InstallationRepository(api,
            store,
            object : FcmTokenProvider { override suspend fun currentToken() = "unused" },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())

        val startup = async { repository.initialize() }
        val sync = async { repository.syncPendingTokenOnce() }
        startup.await(); sync.await()

        assertTrue(api.updated.contains("token-X"))
        assertEquals(null, pending.load())
    }

    @Test fun `concurrent recovery puts pending token once on fresh credentials`() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val api = object : Api() {
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                updates++; updated += fcmToken
                if (updates == 1) { entered.complete(Unit); release.await(); throw Stale() }
            }
        }
        val store = Store(DeviceStore.Credentials("old", "secret"))
        val pending = InMemoryPendingFcmTokenStore().also { it.save("token-X") }
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider { override suspend fun currentToken() = "token-Y" },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())

        val tokenSync = async { repository.syncPendingTokenOnce() }
        entered.await()
        var recoveryAttempts = 0
        val recovery = async { repository.authenticatedCall { recoveryAttempts++; if (recoveryAttempts == 1) throw Stale() else "ok" } }
        release.complete(Unit)
        runCatching { recovery.await() }
        tokenSync.await()

        assertEquals(2, api.updates)
        assertEquals(listOf("token-X", "token-X"), api.updated)
    }

    @Test fun `second 401 on recovered fresh PUT invalidates and retains pending`() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val api = object : Api() {
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                updates++; updated += fcmToken
                if (updates == 1) { entered.complete(Unit); release.await(); throw Stale() }
                throw Stale()
            }
        }
        val store = Store(DeviceStore.Credentials("old", "secret"))
        val pending = InMemoryPendingFcmTokenStore().also { it.save("token-X") }
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider { override suspend fun currentToken() = "token-Y" },
            backgroundScope, pending, ImmediateFcmTokenRetryScheduler())
        val tokenSync = async { repository.syncPendingTokenOnce() }
        entered.await()
        var recoveryAttempts = 0
        val recovery = async { repository.authenticatedCall { recoveryAttempts++; if (recoveryAttempts == 1) throw Stale() else "ok" } }
        release.complete(Unit)
        runCatching { recovery.await() }
        tokenSync.await()

        assertTrue(repository.state.value is InstallationState.Unavailable)
        assertEquals(null, store.value)
        assertEquals("token-X", pending.load())
    }
}
