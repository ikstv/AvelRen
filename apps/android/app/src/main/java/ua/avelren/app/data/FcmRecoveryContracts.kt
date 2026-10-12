package ua.avelren.app.data

enum class RecoveryPhase { PENDING, ROTATION_REQUESTED, ROTATED, ATTACHING, CONFLICT_BLOCKED }

/**
 * Version 1 fields: PENDING has a candidate (source retained when budget is spent).
 * ROTATION_REQUESTED has candidate == source and budget 0.
 * ROTATED has source and budget 1; candidate is null while fetching, or differs from source.
 * ATTACHING has a candidate. CONFLICT_BLOCKED has candidate, source and budget 1.
 * Budget 1 always retains source. Store CAS advances revision by one, never reduces
 * generation/budget, and never changes incident identity before a successful clear.
 */
data class RecoveryRecord(
    val formatVersion: Int,
    val revision: Long,
    val incidentId: String,
    val generation: Long,
    val phase: RecoveryPhase,
    val candidateToken: String?,
    val rotationSourceToken: String?,
    val completedRotations: Int,
) {
    override fun toString() = "RecoveryRecord(version=$formatVersion, revision=$revision, generation=$generation, phase=$phase, rotations=$completedRotations)"
}

/** Corrupt state/failed migration is blocked; callers must not reset the incident. */
class RecoveryStorageException : IllegalStateException("Recovery storage unavailable")

interface RecoveryStore {
    suspend fun load(): RecoveryRecord?
    suspend fun compareAndSet(expected: RecoveryRecord?, replacement: RecoveryRecord?): Boolean
}

interface CredentialCommitter {
    suspend fun commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?): Boolean
}

interface RotatingTokenSource {
    suspend fun currentToken(): String
    suspend fun deleteCurrentToken()
}

interface RecoveryApi {
    suspend fun register(token: String): DeviceStore.Credentials
    suspend fun update(creds: DeviceStore.Credentials, token: String)
    fun isStale(error: Throwable): Boolean
    fun isTokenConflict(error: Throwable): Boolean
}

sealed interface PushSyncState {
    data object Pending : PushSyncState
    data object Synced : PushSyncState
    data object Retrying : PushSyncState
    data object Rejected : PushSyncState
    data object ConflictBlocked : PushSyncState
    data object StorageFailed : PushSyncState
}
