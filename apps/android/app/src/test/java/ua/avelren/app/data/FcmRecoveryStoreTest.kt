package ua.avelren.app.data

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class FcmRecoveryStoreTest {
    private class Preferences : RecoveryPreferences {
        override val lock = Any()
        val disk = mutableMapOf<String, String>()
        var fail = false
        var commits = 0
        override fun get(key: String) = disk[key]
        override fun commit(changes: Map<String, String?>): Boolean {
            commits++
            if (fail) return false
            changes.forEach { (k, v) -> if (v == null) disk.remove(k) else disk[k] = v }
            return true
        }
    }
    private fun record() = RecoveryRecord(1, 1, UUID.randomUUID().toString(), 1, RecoveryPhase.PENDING, "candidate", null, 0)

    @Test fun test_legacy_pending_migration_atomic() = runBlocking {
        val p = Preferences().apply { disk["pending_fcm_token"] = "legacy"; disk["notif_asked"] = "true"; disk["bg_delivery_hint_dismissed"] = "true" }
        val r = DeviceRecoveryStore(p).load()!!
        assertEquals("legacy", r.candidateToken)
        assertEquals(1, p.commits)
        assertNull(p.disk["pending_fcm_token"])
        assertEquals("true", p.disk["notif_asked"])
        assertEquals("true", p.disk["bg_delivery_hint_dismissed"])
        assertEquals(r, DeviceRecoveryStore(p).load())
    }
    @Test fun test_revision_cas_no_newer_clear() = runBlocking {
        val s = DeviceRecoveryStore(Preferences()); val a = record()
        assertTrue(s.compareAndSet(null, a))
        val b = a.copy(revision = 2, generation = 2, candidateToken = "new")
        assertTrue(s.compareAndSet(a, b))
        assertFalse(s.compareAndSet(a, null))
        assertFalse(s.compareAndSet(b.copy(phase = RecoveryPhase.ATTACHING), null))
        assertEquals(b, s.load())
    }
    @Test fun test_commit_failure_preserves_record() = runBlocking {
        val p = Preferences(); val s = DeviceRecoveryStore(p); val a = record()
        assertTrue(s.compareAndSet(null, a)); p.fail = true
        assertFalse(s.compareAndSet(a, null))
        assertEquals(a, DeviceRecoveryStore(p).load())
    }
    @Test fun test_failed_migration_preserves_legacy() = runBlocking {
        val p = Preferences().apply { disk["pending_fcm_token"] = "legacy"; fail = true }
        try { DeviceRecoveryStore(p).load(); fail("Must block") } catch (_: RecoveryStorageException) { }
        assertEquals("legacy", p.disk["pending_fcm_token"])
        assertNull(p.disk["fcm_recovery_record"])
    }
    @Test fun test_credential_commit_before_ready() = runBlocking {
        val p = Preferences(); val s = DeviceRecoveryStore(p)
        val a = DeviceStore.Credentials("id-a", "secret-a"); val b = DeviceStore.Credentials("id-b", "secret-b")
        p.fail = true; assertFalse(s.commit(null, a)); assertNull(p.disk["device_id"])
        p.fail = false; assertTrue(s.commit(null, a))
        assertFalse(s.commit(null, b)); assertFalse(s.commit(a.copy(deviceSecret = "wrong"), null))
        assertEquals("secret-a", p.disk["device_secret"]); assertTrue(s.commit(a, b))
    }
    @Test fun test_corrupt_phase_blocked() = runBlocking {
        val p = Preferences().apply { disk["fcm_recovery_record"] = "corrupt-token-secret"; disk["pending_fcm_token"] = "legacy" }
        val s = DeviceRecoveryStore(p)
        try { s.load(); fail("Must block") } catch (e: RecoveryStorageException) { assertFalse(e.toString().contains("corrupt-token-secret")) }
        assertFalse(s.compareAndSet(null, record())); assertEquals(0, p.commits)
        assertEquals("legacy", p.disk["pending_fcm_token"])
    }
    @Test fun test_completed_rotation_budget_persists() = runBlocking {
        val p = Preferences(); val r = record().copy(phase = RecoveryPhase.ATTACHING, rotationSourceToken = "source", completedRotations = 1)
        assertTrue(DeviceRecoveryStore(p).compareAndSet(null, r)); assertEquals(r, DeviceRecoveryStore(p).load())
        assertFalse(DeviceRecoveryStore(p).compareAndSet(r, r.copy(revision = 2, completedRotations = 0)))
        assertFalse(r.toString().contains("candidate"))
        assertFalse(DeviceStore.Credentials("private-id", "private-secret").toString().contains("private"))
    }
    @Test fun test_overflow_refuses_replacement() = runBlocking {
        val s = DeviceRecoveryStore(Preferences()); val r = record().copy(revision = Long.MAX_VALUE, generation = Long.MAX_VALUE)
        assertTrue(s.compareAndSet(null, r)); assertFalse(s.compareAndSet(r, r.copy(revision = 1, generation = 1)))
        assertEquals(r, s.load())
    }

    @Test fun failed_commit_memory_mutation_is_never_published_or_retried() = runBlocking {
        val disk = mutableMapOf<String, String>()
        val memory = mutableMapOf<String, String>()
        var failCommit = false
        val raw = object : RecoveryPreferences {
            override val lock = Any()
            override fun get(key: String) = memory[key]
            override fun commit(changes: Map<String, String?>): Boolean {
                changes.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }
                if (failCommit) return false
                disk.clear(); disk.putAll(memory)
                return true
            }
        }
        val acknowledged = AcknowledgedRecoveryPreferences(raw)
        val s = DeviceRecoveryStore(acknowledged)
        val r = record()
        assertTrue(s.compareAndSet(null, r))
        failCommit = true
        assertFalse(s.compareAndSet(r, r.copy(revision = 2, generation = 2, candidateToken = "later")))
        assertEquals(r, DeviceRecoveryStore(acknowledged).load())
        assertFalse(s.commit(null, DeviceStore.Credentials("unconfirmed-id", "unconfirmed-secret")))
        assertNull(DeviceRecoveryStore.credentials(acknowledged))
        failCommit = false
        assertFalse(s.compareAndSet(r, null))
        assertFalse(acknowledged.editUnrelated { memory["notif_asked"] = "true"; disk.putAll(memory) })
        assertNull(memory["notif_asked"])
        // Genuine recreation reloads durable bytes, not the previous process memory map.
        val recreated = Preferences().apply { this.disk.putAll(disk) }
        assertEquals(r, DeviceRecoveryStore(recreated).load())
    }

    @Test fun every_phase_survives_recreation_and_invalid_fields_are_refused() = runBlocking {
        val base = record()
        val records = listOf(base,
            base.copy(phase = RecoveryPhase.ROTATION_REQUESTED, rotationSourceToken = "candidate"),
            base.copy(phase = RecoveryPhase.ROTATED, candidateToken = null, rotationSourceToken = "source", completedRotations = 1),
            base.copy(phase = RecoveryPhase.ROTATED, rotationSourceToken = "source", completedRotations = 1),
            base.copy(phase = RecoveryPhase.ATTACHING),
            base.copy(phase = RecoveryPhase.CONFLICT_BLOCKED, rotationSourceToken = "source", completedRotations = 1),
            base.copy(rotationSourceToken = "source", completedRotations = 1))
        for (r in records) {
            val p = Preferences()
            assertTrue(DeviceRecoveryStore(p).compareAndSet(null, r))
            assertEquals(r, DeviceRecoveryStore(p).load())
        }
        for (r in listOf(base.copy(formatVersion = 2), base.copy(revision = 0), base.copy(generation = -1),
            base.copy(incidentId = "bad"), base.copy(candidateToken = ""), base.copy(completedRotations = 2),
            base.copy(phase = RecoveryPhase.ROTATED, rotationSourceToken = "candidate", completedRotations = 1),
            base.copy(phase = RecoveryPhase.CONFLICT_BLOCKED))) {
            assertFalse(DeviceRecoveryStore(Preferences()).compareAndSet(null, r))
        }
    }

    @Test fun failed_credential_write_cannot_become_ready_from_memory() = runBlocking {
        val memory = mutableMapOf<String, String>()
        val raw = object : RecoveryPreferences {
            override val lock = Any()
            override fun get(key: String) = memory[key]
            override fun commit(changes: Map<String, String?>): Boolean {
                changes.forEach { (k, v) -> if (v == null) memory.remove(k) else memory[k] = v }
                return false
            }
        }
        val p = AcknowledgedRecoveryPreferences(raw)
        assertFalse(DeviceRecoveryStore(p).commit(null, DeviceStore.Credentials("new-id", "new-secret")))
        assertEquals("new-id", memory["device_id"])
        assertNull(DeviceRecoveryStore.credentials(p))
        assertFalse(DeviceRecoveryStore(p).commit(null, DeviceStore.Credentials("other-id", "other-secret")))
        assertNull(DeviceRecoveryStore.credentials(p))
        assertNull(DeviceRecoveryStore.credentials(AcknowledgedRecoveryPreferences(Preferences())))
    }
}
