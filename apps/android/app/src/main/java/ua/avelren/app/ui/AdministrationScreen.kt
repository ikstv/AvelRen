package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import ua.avelren.app.AvelRenApp
import ua.avelren.app.data.Api
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal interface AdminAccessClient {
    suspend fun status(): Api.AdminAccess
    suspend fun unlock(password: String): Api.AdminAccess
}

@Composable
internal fun AdministrationSettings(
    modifier: Modifier = Modifier,
    client: AdminAccessClient? = null,
) {
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
                Icon(Icons.Default.AdminPanelSettings, contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary)
                Text("Адміністрування", Modifier.weight(1f), fontWeight = FontWeight.Bold)
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null)
            }
        } else {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { opened = false }) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
                }
                Text("Адміністрування", style = MaterialTheme.typography.titleMedium)
            }
            TabRow(selectedTabIndex = tab, containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary) {
                listOf("Сервер", "Admin").forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = { tab = index },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        text = { Text(label, fontWeight = FontWeight.Bold) })
                }
            }
            if (tab == 1) {
                val application = LocalContext.current.applicationContext
                val access = client ?: remember(application) {
                    val installation = (application as AvelRenApp).installation
                    object : AdminAccessClient {
                        override suspend fun status() =
                            installation.authenticatedCall { Api.adminAccess(it) }
                        override suspend fun unlock(password: String) =
                            installation.authenticatedCall { Api.unlockAdmin(it, password) }
                    }
                }
                AdminAccessForm(access, Modifier.fillMaxWidth().weight(1f))
            }
        }
    }
}

@Composable
private fun AdminAccessForm(access: AdminAccessClient, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    var status by remember { mutableStateOf<Api.AdminAccess?>(null) }
    // PIN and authenticated screen state must not survive leaving this screen.
    var pin by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        busy = true
        error = null
        try {
            status = access.status()
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
            "preview_authorized" -> Text("Тестовий вхід виконано. Права адміністратора не змінено.")
            "awaiting_approval" -> Text("Ця інсталяція очікує підтвердження адміністратора.")
            "unavailable" -> Text("Адміністрування ще не налаштовано.")
            "blocked" -> {
                val until = current.locked_until?.let {
                    runCatching {
                        DateTimeFormatter.ofPattern("dd.MM.yyyy HH:mm")
                            .withZone(ZoneId.of("Europe/Kyiv")).format(Instant.parse(it))
                    }.getOrNull()
                }
                Text(if (until != null) "Вхід заблоковано до $until." else "Вхід тимчасово заблоковано.")
            }
            "ready", "invalid_pin" -> {
                OutlinedTextField(
                    value = pin,
                    onValueChange = { value ->
                        if (value.length <= 128) pin = value
                    },
                    label = { Text("Пароль") },
                    shape = RoundedCornerShape(8.dp),
                    singleLine = true,
                    enabled = !busy,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (current.state == "invalid_pin") {
                    Text("Неправильний пароль. Залишилося спроб: ${current.attempts_remaining}.")
                }
                Button(
                    shape = RoundedCornerShape(12.dp),
                    enabled = !busy && pin.isNotEmpty(),
                    onClick = {
                        focusManager.clearFocus()
                        keyboard?.hide()
                        val submitted = pin
                        pin = ""
                        busy = true
                        error = null
                        scope.launch {
                            try {
                                status = access.unlock(submitted)
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
                    modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) { Text("Увійти", fontWeight = FontWeight.Black) }
            }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (busy) CircularProgressIndicator(Modifier.size(24.dp))
        if (!busy && current?.state !in listOf("ready", "invalid_pin", "authorized", "preview_authorized")) {
            TextButton(onClick = { scope.launch { load() } }) { Text("Оновити стан") }
        }
    }
}
