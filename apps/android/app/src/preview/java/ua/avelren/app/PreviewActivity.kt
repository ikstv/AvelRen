package ua.avelren.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.Api
import ua.avelren.app.ui.AdminAccessClient
import ua.avelren.app.ui.SettingsDeveloperFooter
import ua.avelren.app.ui.SettingsScreen
import ua.avelren.app.ui.theme.AvelRenTheme
import ua.avelren.app.ui.theme.DarkColors
import java.time.Instant

/** Offline visual check: a separate package, no Firebase or production credentials. */
class PreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AvelRenTheme {
                MaterialTheme(colorScheme = DarkColors) {
                    val surgeMode = intent.getStringExtra("surge_mode")
                    if (surgeMode != null) {
                        val client = remember { DemoSurgeClient(surgeMode) }
                        ua.avelren.app.ui.SurgeMonitorScreen(
                            repository = client, onBack = { finish() },
                            notificationsAllowed = ua.avelren.app.notify.Notifications.surgeChannelAllowed(this@PreviewActivity),
                        )
                        return@MaterialTheme
                    }
                    val demo = remember { DemoAccess() }
                    Column(
                        Modifier.fillMaxSize().background(Color(0xFF0A0A0A))
                            .windowInsetsPadding(WindowInsets.systemBars).padding(horizontal = 20.dp),
                    ) {
                        Text(
                            "ТЕСТ • БЕЗ ДОСТУПУ ДО СЕРВЕРА",
                            color = Color(0xFFF5C400),
                            style = MaterialTheme.typography.labelSmall,
                            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                        )
                        SettingsScreen(Modifier.fillMaxWidth().weight(1f), demo)
                        SettingsDeveloperFooter(Modifier.fillMaxWidth().padding(bottom = 16.dp))
                    }
                }
            }
        }
    }
}

private class DemoAccess : AdminAccessClient {
    private var failures = 0
    private var blockedUntil: String? = null
    override suspend fun status() = blockedUntil?.let {
        Api.AdminAccess("blocked", locked_until = it)
    } ?: Api.AdminAccess("ready", attempts_remaining = 3 - failures)

    override suspend fun unlock(password: String): Api.AdminAccess {
        if (blockedUntil != null) return status()
        // Public demonstration value, unrelated to the owner's real server password.
        if (password == "preview") {
            failures = 0
            return Api.AdminAccess("preview_authorized")
        }
        failures += 1
        if (failures >= 3) {
            blockedUntil = Instant.now().plusSeconds(86400).toString()
            return status()
        }
        return Api.AdminAccess("invalid_pin", attempts_remaining = 3 - failures)
    }
}


private class DemoSurgeClient(private val mode: String) : ua.avelren.app.data.SurgeMonitorClient {
    private val cps = listOf(
        ua.avelren.app.data.SurgeCheckpoint(17, "Чоп", "Угорщина", "🇭🇺", true, true, true),
        ua.avelren.app.data.SurgeCheckpoint(6, "Краківець", "Польща", "🇵🇱", true, true, true),
    ) + (40..51).map { ua.avelren.app.data.SurgeCheckpoint(it, "Тестовий КПП $it", fact_supported = true) }
    private var subs = cps.take(2).map { ua.avelren.app.data.SurgeSubscription(it.checkpoint_id, it.title, true, true) }
    override suspend fun checkpoints(): List<ua.avelren.app.data.SurgeCheckpoint> {
        if (mode == "loading") kotlinx.coroutines.delay(Long.MAX_VALUE)
        if (mode == "error") error("synthetic offline")
        return cps
    }
    override suspend fun subscriptions() = subs
    override suspend fun snapshot(checkpointId: Int) = ua.avelren.app.data.SurgeStatus(
        checkpointId, if (checkpointId == 17) "started" else "risk",
        window_start = Instant.now().plusSeconds(3600).toString(),
        window_end = Instant.now().plusSeconds(86400).toString(),
        expires_at = Instant.now().plusSeconds(3600).toString(), forecast_supported = true,
    )
    override suspend fun setSubscription(checkpointId: Int, forecast: Boolean, fact: Boolean) {
        val cp = cps.first { it.checkpoint_id == checkpointId }
        subs = subs.filterNot { it.checkpoint_id == checkpointId } +
            ua.avelren.app.data.SurgeSubscription(checkpointId, cp.title, forecast, fact)
    }
    override suspend fun removeSubscription(checkpointId: Int) { subs = subs.filterNot { it.checkpoint_id == checkpointId } }
}
