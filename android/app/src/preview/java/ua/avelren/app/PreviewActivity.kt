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
