package ua.avelren.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.*
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import ua.avelren.app.data.Api
import ua.avelren.app.ui.AdminAccessClient
import ua.avelren.app.ui.theme.AvelRenTheme
import java.time.Instant

/** Offline visual check: a separate package, no Firebase or production credentials. */
class PreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AvelRenTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val surgeMode = intent.getStringExtra("surge_mode")
                    if (surgeMode != null) {
                        val client = remember { DemoSurgeClient(surgeMode) }
                        ua.avelren.app.ui.SurgeMonitorScreen(
                            repository = client, onBack = { finish() },
                            notificationsAllowed = ua.avelren.app.notify.Notifications.surgeChannelAllowed(this@PreviewActivity),
                            enqueueAck = {},
                        )
                        return@Surface
                    }
                    val demo = remember { DemoAccess() }
                    val localServer = remember {
                        object : ua.avelren.app.ui.AdminServerClient {
                            override suspend fun serverCpuStatus(): Api.ServerCpuStatus {
                                val fixture = intent.getStringExtra("cpu_fixture")
                                if (fixture == "error") error("Synthetic offline")
                                val cpu = when (fixture) {
                                    "0" -> 0.0
                                    "50" -> 50.0
                                    "100" -> 100.0
                                    "null" -> null
                                    else -> 37.0
                                }
                                val measured = Instant.now().minusSeconds(if (fixture == "stale") 301 else 0)
                                return Api.ServerCpuStatus(cpu, measured.toString(), 1, fixture == "stale")
                            }
                        }
                    }
                    val unavailable = {
                        android.widget.Toast.makeText(this@PreviewActivity,
                            "Недоступно в тестовій збірці", android.widget.Toast.LENGTH_SHORT).show()
                    }
                    var scenario by remember { mutableStateOf(PreviewScenario.FORECAST) }
                    var generation by remember { mutableStateOf(0) }
                    val client = remember { PreviewAppClient() }
                    ua.avelren.app.ui.AvelRenScreen(
                        permissionState = ua.avelren.app.data.NotificationPermissionState.Granted,
                        onOpenNotificationSettings = unavailable,
                        screenClient = client, surgeClient = client,
                        adminClient = demo, enqueueSurgeAck = client::acknowledge,
                        adminServerClient = localServer,
                        onOpenPrivacyPolicy = unavailable,
                        onStartUpdate = unavailable,
                        refreshVersion = generation,
                    )
                    // Службове меню не змінює геометрію звичайного екрана.
                    // Відкривається лише явним запуском із preview_controls=true.
                    var controlsVisible by remember {
                        mutableStateOf(intent.getBooleanExtra("preview_controls", false))
                    }
                    if (controlsVisible) {
                        AlertDialog(
                            onDismissRequest = { controlsVisible = false },
                            title = { Text("Локальні тестові дані") },
                            text = {
                                Column {
                                    PreviewScenario.entries.forEach { choice ->
                                        TextButton(onClick = {
                                            scenario = choice
                                            client.setScenario(choice)
                                            generation++
                                            controlsVisible = false
                                        }) {
                                            Text(if (scenario == choice) "✓ ${choice.label}" else choice.label)
                                        }
                                    }
                                }
                            },
                            confirmButton = {
                                TextButton(onClick = { controlsVisible = false }) { Text("Закрити") }
                            },
                        )
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
    private var subs = cps.take(2).map { cp ->
        val kind = if (cp.checkpoint_id == 17) "surge_started" else "surge_forecast"
        val body = if (cp.checkpoint_id == 17) "Почалось зростання черги на Чопі"
            else "Можливий початок масової реєстрації на Краківці"
        ua.avelren.app.data.SurgeSubscription(cp.checkpoint_id, cp.title, true, true,
            alerts = listOf(ua.avelren.app.data.SurgeAlert(99000L + cp.checkpoint_id,
                cp.checkpoint_id.toLong(), cp.checkpoint_id, kind,
                Instant.now().plusSeconds(3600).toString(), cp.title, body)))
    }
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
