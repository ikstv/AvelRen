package ua.avelren.app.data

import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import ua.avelren.app.data.DeviceStore.Credentials

class FcmRecoveryCoordinatorTest {
    private class Conflict : RuntimeException()
    private class Stale : RuntimeException()
    private val old = Credentials("old-device", "old-secret")
    private val fresh = Credentials("new-device", "new-secret")

    private class Records(var value: RecoveryRecord? = null) : RecoveryStore {
        var fail = false
        var corrupt = false
        val history = mutableListOf<RecoveryRecord?>()
        override suspend fun load(): RecoveryRecord? {
            if (corrupt) throw RecoveryStorageException()
            return value
        }
        override suspend fun compareAndSet(expected: RecoveryRecord?, replacement: RecoveryRecord?): Boolean {
            if (fail || value != expected) return false
            value = replacement
            history += replacement
            return true
        }
    }

    private inner class Fixture(seed: Credentials? = null, record: RecoveryRecord? = null) {
        var creds = seed
        var commitFails = false
        val records = Records(record)
        var token = "X"
        var deletes = 0
        var delete: suspend () -> Unit = { token = "Y" }
        var fetch: suspend () -> String = { token }
        var enqueues = 0
        var enqueueFails = false
        var schedule: suspend () -> ScheduleResult = {
            if (enqueueFails) ScheduleResult.Failed(IOException()) else ScheduleResult.Enqueued
        }
        var registrations = 0
        val updates = mutableListOf<Pair<Credentials, String>>()
        var post: suspend (String) -> Credentials = { fresh }
        var put: suspend (Credentials, String) -> Unit = { _, _ -> }
        val coordinator get() = FcmRecoveryCoordinator(
            object : RecoveryApi {
                override suspend fun register(token: String): Credentials {
                    assertTrue("durable enqueue before HTTP", enqueues > 0)
                    assertEquals(RecoveryPhase.ATTACHING, records.value?.phase)
                    registrations++
                    return post(token)
                }
                override suspend fun update(creds: Credentials, token: String) {
                    assertTrue("durable enqueue before HTTP", enqueues > 0)
                    updates += creds to token
                    put(creds, token)
                }
                override fun isStale(error: Throwable) = error is Stale
                override fun isTokenConflict(error: Throwable) = error is Conflict
            }, { creds },
            object : CredentialCommitter {
                override suspend fun commit(expected: Credentials?, replacement: Credentials?): Boolean {
                    if (commitFails || creds != expected) return false
                    creds = replacement
                    return true
                }
            }, records,
            object : RotatingTokenSource {
                override suspend fun currentToken() = fetch()
                override suspend fun deleteCurrentToken() {
                    assertEquals(RecoveryPhase.ROTATION_REQUESTED, records.value?.phase)
                    deletes++
                    delete()
                }
            }, object : FcmTokenRetryScheduler {
                override suspend fun enqueue(): ScheduleResult {
                    assertNotNull(records.value)
                    enqueues++
                    return schedule()
                }
            },
        )
    }

    private fun record(phase: RecoveryPhase, budget: Int = 0, candidate: String? = "X") = RecoveryRecord(
        1, 1, UUID.randomUUID().toString(), 1, phase, candidate,
        if (budget == 1 || phase == RecoveryPhase.ROTATION_REQUESTED) "X" else null, budget,
    )

    // Clearing credentials on a valid PUT409 would lose the existing identity.
    @Test fun test_put409_preserves_creds() = runTest {
        val f = Fixture(old)
        f.put = { _, token -> if (token == "X") throw Conflict() }
        val c = f.coordinator
        c.initialize()
        assertEquals(old, f.creds)
        assertEquals(InstallationState.Ready("old-device"), c.state.value)
        assertEquals(PushSyncState.Synced, c.pushState.value)
        assertEquals(listOf(old to "X", old to "Y"), f.updates)
        assertEquals(0, f.registrations)
        assertEquals(1, f.deletes)
        assertNull(f.records.value)
    }

    // A lost POST response must retain work, then rotate rather than recover an unknown secret.
    @Test fun test_lost_post_response() = runTest {
        val f = Fixture()
        var first = true
        f.post = { token ->
            if (first) { first = false; throw IOException() }
            if (token == "X") throw Conflict()
            fresh
        }
        val c = f.coordinator
        c.initialize()
        assertNull(f.creds)
        assertEquals(RecoveryPhase.ATTACHING, f.records.value?.phase)
        assertEquals(PendingTokenSyncOutcome.Synced, c.syncOnce())
        assertEquals(fresh, f.creds)
        assertEquals(1, f.deletes)
        assertEquals(1, f.enqueues)
    }

    // Retrying/recreating a blocked incident must not reset its rotation budget.
    @Test fun test_rotation_once_then_blocked() = runTest {
        val f = Fixture(old)
        f.put = { _, _ -> throw Conflict() }
        val c = f.coordinator
        c.initialize()
        val blocked = f.records.value!!
        assertEquals(RecoveryPhase.CONFLICT_BLOCKED, blocked.phase)
        assertEquals(1, blocked.completedRotations)
        assertEquals(PushSyncState.ConflictBlocked, c.pushState.value)
        c.syncOnce()
        f.coordinator.initialize()
        assertEquals(1, f.deletes)
        assertEquals(2, f.updates.size)
        f.token = "Z"
        c.providerSignal()
        assertEquals(1, f.records.value?.completedRotations)
        assertEquals(1, f.deletes)
        assertEquals(old to "Z", f.updates.last())
    }

    // Every durable phase can resume; blocked records require a new signal.
    @Test fun test_resume_all_phases() = runTest {
        for (phase in RecoveryPhase.entries) {
            val budget = if (phase == RecoveryPhase.ROTATED || phase == RecoveryPhase.CONFLICT_BLOCKED) 1 else 0
            val candidate = if (budget == 1) "Y" else "X"
            val f = Fixture(old, record(phase, budget, candidate))
            f.token = candidate
            val c = f.coordinator
            c.initialize()
            if (phase == RecoveryPhase.CONFLICT_BLOCKED) {
                assertEquals(PushSyncState.ConflictBlocked, c.pushState.value)
                assertTrue(f.updates.isEmpty())
            } else {
                assertEquals(PushSyncState.Synced, c.pushState.value)
                assertNull(f.records.value)
            }
            assertEquals(if (phase == RecoveryPhase.ROTATION_REQUESTED) 1 else 0, f.deletes)
        }
    }

    // Ambiguous delete must reread provider before attempting another delete.
    @Test fun test_delete_timeout_provider_changed() = runTest {
        val f = Fixture(old)
        f.put = { _, token -> if (token == "X") throw Conflict() }
        f.delete = { f.token = "Y"; throw IOException() }
        val c = f.coordinator
        c.initialize()
        assertEquals(RecoveryPhase.ROTATION_REQUESTED, f.records.value?.phase)
        c.syncOnce()
        assertEquals(1, f.deletes)
        assertEquals(PushSyncState.Synced, c.pushState.value)
    }

    @Test fun test_callback_x_during_y() = runTest {
        val f = Fixture(old)
        f.token = "Y" // callback X is merely a signal; there is no token argument to trust.
        val c = f.coordinator
        c.providerSignal()
        assertEquals(listOf(old to "Y"), f.updates)
        assertEquals(PushSyncState.Synced, c.pushState.value)
    }

    // Concurrent stale callers share recovery even when registration needs rotation.
    @Test fun test_parallel401_conflict() = runTest {
        val f = Fixture(old)
        f.post = { if (it == "X") throw Conflict() else fresh }
        val c = f.coordinator
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var oldCalls = 0
        suspend fun call() = c.authenticatedCall { creds ->
            if (creds == old) {
                oldCalls++
                if (oldCalls == 2) entered.complete(Unit)
                release.await()
                throw Stale()
            }
            creds.deviceId
        }
        val a = async { call() }
        val b = async { call() }
        entered.await()
        release.complete(Unit)
        assertEquals("new-device", a.await())
        assertEquals("new-device", b.await())
        assertEquals(2, f.registrations)
        assertEquals(1, f.deletes)
        assertEquals(fresh, f.creds)
    }

    @Test fun test_second401_no_loop() = runTest {
        val f = Fixture(old)
        val c = f.coordinator
        var calls = 0
        try { c.authenticatedCall<Unit> { calls++; throw Stale() }; fail() } catch (_: Stale) { }
        assertEquals(2, calls)
        assertEquals(1, f.registrations)
        assertNull(f.creds)
        assertTrue(c.state.value is InstallationState.Unavailable)
    }

    @Test fun test_failed_commit_no_ready() = runTest {
        val f = Fixture()
        f.commitFails = true
        val c = f.coordinator
        c.initialize()
        assertNull(f.creds)
        assertFalse(c.state.value is InstallationState.Ready)
        assertEquals(PushSyncState.StorageFailed, c.pushState.value)
        assertNotNull(f.records.value)
        c.syncOnce()
        assertEquals(1, f.registrations)
    }

    // An old POST result cannot publish credentials or clear a newer generation.
    @Test fun test_newer_pending_not_cleared() = runTest {
        val f = Fixture()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        f.post = { entered.complete(Unit); release.await(); fresh }
        val c = f.coordinator
        val first = async { c.providerSignal() }
        entered.await()
        val before = f.records.value!!
        val newer = before.copy(revision = before.revision + 1, generation = before.generation + 1, phase = RecoveryPhase.PENDING, candidateToken = "Y")
        assertTrue(f.records.compareAndSet(before, newer))
        f.token = "Y"
        release.complete(Unit)
        first.await()
        assertNull(f.creds)
        assertEquals(newer, f.records.value)
        assertEquals(PushSyncState.Retrying, c.pushState.value)
    }

    @Test fun corrupt_storage_stays_blocked() = runTest {
        val f = Fixture(old)
        f.records.corrupt = true
        val c = f.coordinator
        c.initialize()
        c.providerSignal()
        c.syncOnce()
        assertEquals(PushSyncState.StorageFailed, c.pushState.value)
        assertEquals(old, f.creds)
        assertEquals(0, f.enqueues)
        assertTrue(f.updates.isEmpty())
    }

    @Test fun enqueue_failure_preserves_pending_and_does_not_start_http() = runTest {
        val f = Fixture()
        f.enqueueFails = true
        val c = f.coordinator
        c.providerSignal()
        assertEquals(RecoveryPhase.PENDING, f.records.value?.phase)
        assertEquals(PushSyncState.Retrying, c.pushState.value)
        assertEquals(0, f.registrations)
    }

    @Test fun cancellation_preserves_attaching_record() = runTest {
        val f = Fixture()
        f.post = { throw CancellationException() }
        val c = f.coordinator
        try { c.initialize(); fail() } catch (_: CancellationException) { }
        assertEquals(RecoveryPhase.ATTACHING, f.records.value?.phase)
        assertNull(f.creds)
    }

    @Test fun same_token_after_delete_retries_fetch_without_delete_or_http() = runTest {
        val f = Fixture(old)
        f.put = { _, _ -> throw Conflict() }
        f.delete = { }
        val c = f.coordinator
        c.initialize()
        c.syncOnce()
        assertEquals(1, f.deletes)
        assertEquals(1, f.updates.size)
        assertEquals(RecoveryPhase.ROTATED, f.records.value?.phase)
        assertEquals(1, f.records.value?.completedRotations)
        assertEquals(PushSyncState.Retrying, c.pushState.value)
    }

    // A delayed callback is not an explicit user retry or a new provider token.
    @Test fun unchanged_provider_signal_preserves_conflict_blocked() = runTest {
        val f = Fixture(old, record(RecoveryPhase.CONFLICT_BLOCKED, 1, "Y"))
        f.token = "Y"
        val c = f.coordinator
        c.providerSignal()
        assertEquals(RecoveryPhase.CONFLICT_BLOCKED, f.records.value?.phase)
        assertEquals(PushSyncState.ConflictBlocked, c.pushState.value)
        assertTrue(f.updates.isEmpty())
    }

    @Test fun explicit_retry_preserves_budget_and_repeated_conflict_stays_blocked() = runTest {
        val blocked = record(RecoveryPhase.CONFLICT_BLOCKED, 1, "Y")
        val f = Fixture(old, blocked)
        f.token = "Y"
        f.put = { _, _ -> throw Conflict() }
        val c = f.coordinator
        c.retryBlocked()
        assertEquals(listOf(old to "Y"), f.updates)
        assertEquals(RecoveryPhase.CONFLICT_BLOCKED, f.records.value?.phase)
        assertEquals(blocked.incidentId, f.records.value?.incidentId)
        assertEquals(1, f.records.value?.completedRotations)
        assertEquals(0, f.deletes)
        assertEquals(PushSyncState.ConflictBlocked, c.pushState.value)
    }

    @Test fun sdk_fetch_outage_after_delete_retries_only_fetch() = runTest {
        val f = Fixture(old, record(RecoveryPhase.ROTATED, 1, null))
        f.enqueues = 1 // persisted work is already scheduled before this worker entry.
        f.fetch = { throw IllegalStateException("SDK failure") }
        val c = f.coordinator
        assertTrue(c.syncOnce() is PendingTokenSyncOutcome.RetryableFailure)
        assertEquals(RecoveryPhase.ROTATED, f.records.value?.phase)
        assertEquals(0, f.deletes)
        f.fetch = { "Y" }
        assertEquals(PendingTokenSyncOutcome.Synced, c.syncOnce())
        assertEquals(listOf(old to "Y"), f.updates)
        assertEquals(0, f.deletes)
        assertEquals(1, f.enqueues)
    }

    @Test fun obsolete_enqueue_failure_cannot_override_newer_success() = runTest {
        val f = Fixture(old)
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        f.schedule = {
            if (f.enqueues == 1) {
                entered.complete(Unit)
                release.await()
                ScheduleResult.Failed(IOException())
            } else ScheduleResult.Enqueued
        }
        val c = f.coordinator
        val first = async { c.providerSignal() }
        entered.await()
        f.token = "Y"
        c.providerSignal()
        assertEquals(listOf(old to "Y"), f.updates)
        assertNull(f.records.value)
        release.complete(Unit)
        first.await()
        assertEquals(PushSyncState.Synced, c.pushState.value)
        assertNull(f.records.value)
    }

    @Test fun failed_durable_clear_stays_pending_and_blocks_later_writes() = runTest {
        val f = Fixture(old)
        f.put = { _, _ -> f.records.fail = true }
        val c = f.coordinator
        c.initialize()
        assertEquals(RecoveryPhase.ATTACHING, f.records.value?.phase)
        assertEquals(PushSyncState.StorageFailed, c.pushState.value)
        f.records.fail = false
        c.syncOnce()
        assertEquals(1, f.updates.size)
        assertEquals(old, f.creds)
        assertEquals(PushSyncState.StorageFailed, c.pushState.value)
    }
}
