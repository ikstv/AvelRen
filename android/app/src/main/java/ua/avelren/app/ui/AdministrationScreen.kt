package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import ua.avelren.app.AvelRenApp
import ua.avelren.app.data.Api
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
internal fun AdministrationSettings(modifier: Modifier = Modifier) {
    var opened by rememberSaveable { mutableStateOf(false) }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    BackHandler(opened) { opened = false }
    Column(modifier) {
        if (!opened) {
            Row(
                Modifier.fillMaxWidth().clickable { opened = true }.padding(vertical = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Icon(Icons.Default.AdminPanelSettings, contentDescription = null)
                Text("Адміністрування", Modifier.weight(1f))
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null)
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { opened = false }) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
                Text("Адміністрування", style = MaterialTheme.typography.titleMedium)
            }
            TabRow(selectedTabIndex = tab) {
                listOf("Сервер", "Admin").forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = { tab = index }, text = { Text(label) })
                }
            }
            if (tab == 1) AdminAccessForm(Modifier.fillMaxWidth().weight(1f))
        }
    }
}

@Composable
private fun AdminAccessForm(modifier: Modifier = Modifier) {
    val installation = (LocalContext.current.applicationContext as AvelRenApp).installation
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf<Api.AdminAccess?>(null) }
    // PIN and authenticated screen state must not survive leaving this screen.
    var pin by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        busy = true
        error = null
        try {
            status = installation.authenticatedCall { Api.adminAccess(it) }
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            status = null
            error = "Вхід недоступний. Перевірте з’єднання або спробуйте пізніше."
        } finally {
            busy = false
        }
    }
    LaunchedEffect(Unit) { load() }

    Column(
        modifier.verticalScroll(rememberScrollState()).imePadding().padding(vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        val current = status
        when (current?.state) {
            "authorized" -> Text("Цей пристрій — єдиний адміністратор.")
            "awaiting_approval" -> Text("Ця інсталяція очікує підтвердження адміністратора.")
            "unavailable" -> Text("Адміністрування ще не налаштовано.")
            "blocked" -> {
                val until = current.locked_until?.let {
                    runCatching {
                        DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")
                            .withZone(ZoneId.of("Europe/Kyiv")).format(Instant.parse(it))
                    }.getOrNull()
                }
                Text(if (until != null) "Вхід заблоковано до $until (Київ)." else "Вхід тимчасово заблоковано.")
            }
            "ready", "invalid_pin" -> {
                OutlinedTextField(
                    value = pin,
                    onValueChange = { value ->
                        if (value.length <= 4 && value.all { it in '0'..'9' }) pin = value
                    },
                    label = { Text("PIN") },
                    singleLine = true,
                    enabled = !busy,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (current.state == "invalid_pin") {
                    Text("Неправильний PIN. Залишилося спроб: ${current.attempts_remaining}.")
                }
                Button(
                    enabled = !busy && pin.length == 4,
                    onClick = {
                        val submitted = pin
                        pin = ""
                        busy = true
                        error = null
                        scope.launch {
                            try {
                                status = installation.authenticatedCall { Api.unlockAdmin(it, submitted) }
                            } catch (e: CancellationException) {
                                throw e
                            } catch (_: Exception) {
                                // An uncertain response may already have consumed a server-side attempt.
                                status = null
                                error = "Не вдалося підтвердити результат. Оновіть стан перед наступною спробою."
                            } finally {
                                busy = false
                            }
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Увійти") }
            }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (busy) CircularProgressIndicator(Modifier.size(24.dp))
        if (!busy && current?.state !in listOf("ready", "invalid_pin", "authorized")) {
            TextButton(onClick = { scope.launch { load() } }) { Text("Оновити стан") }
        }
    }
}
