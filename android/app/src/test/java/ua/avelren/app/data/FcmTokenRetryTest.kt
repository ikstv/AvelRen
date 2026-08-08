package ua.avelren.app.data

import androidx.work.ListenableWorker
import java.io.IOException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FcmTokenRetryTest {
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
}
