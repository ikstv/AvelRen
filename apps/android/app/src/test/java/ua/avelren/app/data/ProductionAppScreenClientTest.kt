package ua.avelren.app.data

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ProductionAppScreenClientTest {
    @Test fun `monitor snapshot uses initialized installation credentials`() = runTest {
        val stored = DeviceStore.Credentials("device-local", "secret-local")
        val installation = InstallationRepository(
            object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials = error("unexpected registration")
                override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = Unit
                override fun isStaleInstallation(exc: Throwable) = false
            },
            object : CredentialStore {
                override fun load() = stored
                override fun save(creds: DeviceStore.Credentials) = Unit
                override fun clear() = Unit
            },
            WiringTokens("local-token"),
            backgroundScope, recoveryStore = TestRecoveryRecords(), credentialCommitter = object : CredentialCommitter {
                override suspend fun commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?) = false
            },
        )
        installation.initialize()
        val client = ProductionAppScreenClient(installation,
            loadSubscriptions = { credentials ->
                assertEquals("device-local", credentials.deviceId)
                listOf(Api.Subscription(11, 17, "Чоп", threshold = 50))
            },
            loadEtaTargets = { credentials ->
                assertEquals("secret-local", credentials.deviceSecret)
                emptyList()
            },
        )
        assertEquals(listOf(11L), client.monitors().first.map { it.id })
        assertTrue(client.monitors().second.isEmpty())
    }
}
