package ua.avelren.app.data

import android.content.Context
import android.content.SharedPreferences
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.util.Base64
import java.util.UUID
import kotlinx.coroutines.CancellationException

/** Transactions preserve unrelated keys. Reads expose acknowledged values only. */
internal interface RecoveryPreferences {
    val lock: Any
    fun get(key: String): String?
    fun commit(changes: Map<String, String?>): Boolean
}

/** SharedPreferences updates memory even on commit(false). Freeze the acknowledged snapshot
 * and refuse further writes after an ambiguous disk failure until a genuine process restart. */
internal class AcknowledgedRecoveryPreferences(private val delegate: RecoveryPreferences) : RecoveryPreferences {
    override val lock = delegate.lock
    private val snapshot = synchronized(lock) { KEYS.associateWith { delegate.get(it) }.toMutableMap() }
    private var failed = false
    override fun get(key: String): String? = synchronized(lock) { snapshot[key] }
    /** Any later SharedPreferences editor could flush its unacknowledged memory map. */
    fun editUnrelated(edit: () -> Unit): Boolean = synchronized(lock) {
        if (failed) return@synchronized false
        edit()
        true
    }
    override fun commit(changes: Map<String, String?>): Boolean = synchronized(lock) {
        if (failed) return@synchronized false
        val committed = try { delegate.commit(changes) } catch (e: CancellationException) {
            failed = true
            throw e
        } catch (_: Exception) { false }
        if (committed) snapshot.putAll(changes) else failed = true
        committed
    }
    companion object {
        val KEYS = listOf("device_id", "device_secret", "pending_fcm_token", "fcm_recovery_record")
    }
}

internal class SharedRecoveryPreferences(private val prefs: SharedPreferences, override val lock: Any) : RecoveryPreferences {
    override fun get(key: String): String? = try { prefs.getString(key, null) } catch (_: Exception) { throw RecoveryStorageException() }
    override fun commit(changes: Map<String, String?>): Boolean {
        val editor = prefs.edit()
        changes.forEach { (key, value) -> if (value == null) editor.remove(key) else editor.putString(key, value) }
        return editor.commit()
    }
}

class DeviceRecoveryStore internal constructor(private val preferences: RecoveryPreferences) : RecoveryStore, CredentialCommitter {
    constructor(context: Context) : this(DeviceStore.recoveryPreferences(context))

    override suspend fun load(): RecoveryRecord? = synchronized(preferences.lock) { loadLocked() }

    private fun loadLocked(): RecoveryRecord? {
        preferences.get(RECORD)?.let { return decode(it) }
        val legacy = preferences.get(LEGACY) ?: return null
        val migrated = RecoveryRecord(1, 1, UUID.randomUUID().toString(), 1, RecoveryPhase.PENDING, legacy, null, 0)
        val encoded = encode(migrated) ?: throw RecoveryStorageException()
        if (!preferences.commit(mapOf(RECORD to encoded, LEGACY to null))) throw RecoveryStorageException()
        return migrated
    }

    override suspend fun compareAndSet(expected: RecoveryRecord?, replacement: RecoveryRecord?): Boolean = synchronized(preferences.lock) {
        val current = try { loadLocked() } catch (_: RecoveryStorageException) { return@synchronized false }
        if (current != expected) return@synchronized false
        if (replacement != null) {
            if (!valid(replacement)) return@synchronized false
            if (current != null && (
                    current.revision == Long.MAX_VALUE || current.generation == Long.MAX_VALUE ||
                    replacement.revision != current.revision + 1 || replacement.generation < current.generation ||
                    replacement.incidentId != current.incidentId || replacement.completedRotations < current.completedRotations
                )) return@synchronized false
        }
        val encoded = replacement?.let { encode(it) ?: return@synchronized false }
        preferences.commit(mapOf(RECORD to encoded))
    }

    override suspend fun commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?): Boolean =
        synchronized(preferences.lock) { commitCredentials(preferences, expected, replacement) }

    companion object {
        private const val RECORD = "fcm_recovery_record"
        private const val LEGACY = "pending_fcm_token"

        internal fun credentials(p: RecoveryPreferences): DeviceStore.Credentials? {
            val id = p.get("device_id") ?: return null
            val secret = p.get("device_secret") ?: return null
            return DeviceStore.Credentials(id, secret)
        }
        internal fun commitCredentials(p: RecoveryPreferences, expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?): Boolean {
            if (credentials(p) != expected) return false
            if (replacement != null && (replacement.deviceId.isBlank() || replacement.deviceSecret.isBlank())) return false
            return p.commit(mapOf("device_id" to replacement?.deviceId, "device_secret" to replacement?.deviceSecret))
        }

        private fun valid(r: RecoveryRecord): Boolean {
            if (r.formatVersion != 1 || r.revision <= 0 || r.generation <= 0 || r.completedRotations !in 0..1) return false
            if (runCatching { UUID.fromString(r.incidentId).toString().equals(r.incidentId, ignoreCase = true) }.getOrDefault(false).not()) return false
            if (r.candidateToken != null && r.candidateToken.isBlank() || r.rotationSourceToken != null && r.rotationSourceToken.isBlank()) return false
            val candidate = r.candidateToken; val source = r.rotationSourceToken
            if (r.completedRotations == 1 && source == null) return false
            return when (r.phase) {
                RecoveryPhase.PENDING -> candidate != null && (r.completedRotations == 1 || source == null)
                RecoveryPhase.ROTATION_REQUESTED -> candidate != null && candidate == source && r.completedRotations == 0
                RecoveryPhase.ROTATED -> source != null && r.completedRotations == 1 && candidate != source
                RecoveryPhase.ATTACHING -> candidate != null
                RecoveryPhase.CONFLICT_BLOCKED -> candidate != null && source != null && r.completedRotations == 1
            }
        }
        private fun encode(r: RecoveryRecord): String? = try {
            if (!valid(r)) null else {
                val bytes = ByteArrayOutputStream()
                DataOutputStream(bytes).use { out ->
                    out.writeInt(r.formatVersion); out.writeLong(r.revision); out.writeUTF(r.incidentId)
                    out.writeLong(r.generation); out.writeUTF(r.phase.name)
                    out.writeBoolean(r.candidateToken != null); r.candidateToken?.let(out::writeUTF)
                    out.writeBoolean(r.rotationSourceToken != null); r.rotationSourceToken?.let(out::writeUTF)
                    out.writeInt(r.completedRotations)
                }
                Base64.getEncoder().encodeToString(bytes.toByteArray())
            }
        } catch (_: Exception) { null }
        private fun decode(encoded: String): RecoveryRecord = try {
            // Bound parsing before allocation. FCM tokens are much smaller than this.
            if (encoded.length > 180_000) throw RecoveryStorageException()
            val input = DataInputStream(ByteArrayInputStream(Base64.getDecoder().decode(encoded)))
            val r = input.use {
                val record = RecoveryRecord(it.readInt(), it.readLong(), it.readUTF(), it.readLong(),
                    RecoveryPhase.valueOf(it.readUTF()), if (it.readBoolean()) it.readUTF() else null,
                    if (it.readBoolean()) it.readUTF() else null, it.readInt())
                if (it.read() != -1 || !valid(record)) throw RecoveryStorageException()
                record
            }
            r
        } catch (_: Exception) { throw RecoveryStorageException() }
    }
}
