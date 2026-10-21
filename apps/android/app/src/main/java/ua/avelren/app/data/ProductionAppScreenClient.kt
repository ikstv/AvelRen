package ua.avelren.app.data

/** Продуктовий адаптер; API й installation recovery залишаються штатними. */
class ProductionAppScreenClient(
    private val installation: InstallationRepository,
    private val loadSubscriptions: suspend (DeviceStore.Credentials) -> List<Api.Subscription> = { Api.subscriptions(it) },
    private val loadEtaTargets: suspend (DeviceStore.Credentials) -> List<Api.EtaTarget> = { Api.etaTargets(it) },
    private val mutationCredentials: (() -> DeviceStore.Credentials?)? = null,
) : AppScreenClient {
    override suspend fun workload() = Api.workload()
    override suspend fun serverStatus() = Api.serverStatus()
    override suspend fun history(checkpointId: Int) = Api.history(checkpointId, hours = 1)
    override suspend fun forecast(checkpointId: Int) = Api.forecast(checkpointId)
    override suspend fun monitors() = installation.authenticatedCall { credentials ->
        loadMonitorSnapshot({ loadSubscriptions(credentials) }, { loadEtaTargets(credentials) })
    }
    override suspend fun subscribe(checkpointId: Int, threshold: Int) =
        mutate { Api.subscribe(it, checkpointId, threshold) }
    override suspend fun unsubscribe(subscriptionId: Long) =
        mutate { Api.unsubscribe(it, subscriptionId) }
    override suspend fun createEtaTarget(checkpointId: Int, targetAtIso: String) =
        mutate { Api.createEtaTarget(it, checkpointId, targetAtIso) }
    override suspend fun deleteEtaTarget(targetId: Long) =
        mutate { Api.deleteEtaTarget(it, targetId) }

    private suspend fun mutate(call: suspend (DeviceStore.Credentials) -> Unit) {
        val source = mutationCredentials
        if (source == null) installation.authenticatedCall(call)
        else source()?.let { call(it) }
    }
}
