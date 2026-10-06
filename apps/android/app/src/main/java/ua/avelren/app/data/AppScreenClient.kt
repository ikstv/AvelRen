package ua.avelren.app.data

/** Джерело даних спільних екранів; preview не потребує installation чи мережі. */
interface AppScreenClient {
    suspend fun workload(): List<Api.Workload>
    suspend fun serverStatus(): PublicServerStatus
    suspend fun history(checkpointId: Int): Api.History
    suspend fun forecast(checkpointId: Int): Api.Forecast
    suspend fun monitors(): Pair<List<Api.Subscription>, List<Api.EtaTarget>>
    suspend fun subscribe(checkpointId: Int, threshold: Int)
    suspend fun unsubscribe(subscriptionId: Long)
    suspend fun createEtaTarget(checkpointId: Int, targetAtIso: String)
    suspend fun deleteEtaTarget(targetId: Long)
}
