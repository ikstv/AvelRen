package ua.avelren.app.data

import androidx.work.ListenableWorker
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.yield
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
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
    private fun pending() = TestRecoveryRecords(RecoveryRecord(1, 1,
        "11111111-1111-4111-8111-111111111111", 1, RecoveryPhase.PENDING, "token-X", null, 0))

    @Test fun `worker retries when repository is unavailable`() = runTest {
        assertTrue(runFcmTokenSync(null) is ListenableWorker.Result.Retry)
    }
    @Test fun `enqueue failure preserves pending token and makes no HTTP call`() = runTest {
        val api = Api()
        val records = TestRecoveryRecords()
        val store = WiringCredentials(null)
        val repository = InstallationRepository(api, store, WiringTokens("token-X"), backgroundScope,
            records, testCommitter(store), object : FcmTokenRetryScheduler {
                override suspend fun enqueue() = ScheduleResult.Failed(IOException("scheduler offline"))
            })
        repository.onNewFcmToken("obsolete")
        assertEquals("token-X", records.record!!.candidateToken)
        assertEquals(0, api.registrations + api.updates)
        assertEquals(PushSyncState.Retrying, repository.pushState.value)
    }
    @Test fun `save failure does not enqueue or call HTTP`() = runTest {
        var enqueues = 0
        val api = Api()
        val records = TestRecoveryRecords().apply { fail = true }
        val store = WiringCredentials()
        val repository = InstallationRepository(api, store, WiringTokens(), backgroundScope,
            records, testCommitter(store), object : FcmTokenRetryScheduler {
                override suspend fun enqueue(): ScheduleResult { enqueues++; return ScheduleResult.Enqueued }
            })
        repository.onNewFcmToken("obsolete")
        assertEquals(0, enqueues)
        assertEquals(0, api.registrations + api.updates)
        assertEquals(PushSyncState.StorageFailed, repository.pushState.value)
    }
    @Test fun `failure classification is retryable for transport errors`() {
        assertTrue(classifyTokenSyncFailure(IOException("timeout")) is PendingTokenSyncOutcome.RetryableFailure)
    }
    @Test fun `credential registration race synchronizes pending token before clear`() = runTest {
        val api = Api()
        val records = pending()
        val store = WiringCredentials(null)
        val repository = InstallationRepository(api, store, WiringTokens("token-Y"), backgroundScope,
            records, testCommitter(store))
        val registration = async { repository.authenticatedCall { "registered" } }
        yield()
        repository.syncPendingTokenOnce()
        assertEquals("registered", registration.await())
        assertEquals(1, api.registrations)
        assertNull(records.record)
        assertEquals(PushSyncState.Synced, repository.pushState.value)
    }
    @Test fun `self 401 recovery registers token without redundant PUT`() = runTest {
        val api = object : Api() {
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) { updates++; throw Stale() }
        }
        val store = WiringCredentials(DeviceStore.Credentials("old", "secret"))
        val records = TestRecoveryRecords()
        val repository = InstallationRepository(api, store, WiringTokens("token-X"), backgroundScope,
            records, testCommitter(store))
        repository.onNewFcmToken("obsolete")
        assertNull(records.record)
        assertEquals(DeviceStore.Credentials("device-1", "secret-1"), store.value)
        assertEquals(1, api.registrations)
        assertEquals(1, api.updates)
    }
    @Test fun `valid credentials stay Ready and pending survives Firebase outage at startup`() = runTest {
        val api = Api()
        val store = WiringCredentials()
        val records = pending()
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider {
                override suspend fun currentToken() = error("Firebase unavailable")
                override suspend fun deleteCurrentToken() = error("unexpected delete")
            },
            backgroundScope, records, testCommitter(store))
        repository.initialize()
        assertTrue(repository.state.value is InstallationState.Ready)
        assertEquals("token-X", records.record!!.candidateToken)
        assertEquals(DeviceStore.Credentials("valid", "secret"), store.value)
        assertEquals(0, api.updates + api.registrations)
        assertEquals(PushSyncState.Retrying, repository.pushState.value)
    }
    @Test fun `no credentials with saved pending remains unavailable during Firebase outage`() = runTest {
        val api = Api()
        val store = WiringCredentials(null)
        val records = pending()
        val repository = InstallationRepository(api, store,
            object : FcmTokenProvider {
                override suspend fun currentToken() = error("Firebase unavailable")
                override suspend fun deleteCurrentToken() = error("unexpected delete")
            }, backgroundScope, records, testCommitter(store))
        repository.initialize()
        assertTrue(repository.state.value is InstallationState.Unavailable)
        assertEquals("token-X", records.record!!.candidateToken)
        assertNull(store.value)
        assertEquals(0, api.registrations + api.updates)
        assertEquals(PushSyncState.Retrying, repository.pushState.value)
    }
    @Test fun `persisted credential load is serialized with pending sync`() = runTest {
        val api = Api()
        val store = WiringCredentials()
        val records = pending()
        val repository = InstallationRepository(api, store, WiringTokens("token-Y"), backgroundScope,
            records, testCommitter(store))
        val startup = async { repository.initialize() }
        val sync = async { repository.syncPendingTokenOnce() }
        startup.await(); sync.await()
        assertEquals(listOf("token-Y"), api.updated)
        assertNull(records.record)
        assertEquals(0, api.registrations)
    }
    @Test fun `concurrent recovery uses fresh credentials without false clear`() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val api = object : Api() {
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                updates++; updated += fcmToken
                if (updates == 1) { entered.complete(Unit); release.await(); throw Stale() }
            }
        }
        val store = WiringCredentials(DeviceStore.Credentials("old", "secret"))
        val records = pending()
        val repository = InstallationRepository(api, store, WiringTokens("token-Y"), backgroundScope,
            records, testCommitter(store))
        val sync = async { repository.syncPendingTokenOnce() }
        entered.await()
        val recovery = async {
            repository.authenticatedCall { creds -> if (creds.deviceId == "old") throw Stale() else "ok" }
        }
        yield(); release.complete(Unit)
        sync.await(); assertEquals("ok", recovery.await())
        assertEquals(1, api.registrations)
        assertNull(records.record)
        assertEquals("device-1", store.value!!.deviceId)
    }
    @Test fun `second 401 on authenticated retry invalidates without loop`() = runTest {
        val api = Api()
        val store = WiringCredentials(DeviceStore.Credentials("old", "secret"))
        val records = pending()
        val repository = InstallationRepository(api, store, WiringTokens("token-Y"), backgroundScope,
            records, testCommitter(store))
        var attempts = 0
        try {
            repository.authenticatedCall<String> { attempts++; throw Stale() }
            fail("expected 401")
        } catch (_: Stale) { }
        assertEquals(2, attempts)
        assertEquals(1, api.registrations)
        assertNull(store.value)
        assertTrue(repository.state.value is InstallationState.Unavailable)
    }
    @Test fun `cancelled enqueue propagates and preserves durable pending`() = runTest {
        val api = Api()
        val store = WiringCredentials()
        val records = TestRecoveryRecords()
        val repository = InstallationRepository(api, store, WiringTokens("token-X"), backgroundScope,
            records, testCommitter(store), object : FcmTokenRetryScheduler {
                override suspend fun enqueue(): ScheduleResult = throw CancellationException("cancelled")
            })
        try { repository.onNewFcmToken("obsolete"); fail("expected cancellation") }
        catch (_: CancellationException) { }
        assertEquals("token-X", records.record!!.candidateToken)
        assertEquals(0, api.updates + api.registrations)
    }
}
