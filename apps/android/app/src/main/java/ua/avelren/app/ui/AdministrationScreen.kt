package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import io.ktor.client.plugins.ClientRequestException
import io.ktor.http.HttpStatusCode
import ua.avelren.app.AvelRenApp
import ua.avelren.app.BuildConfig
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.ui.theme.SignWarn
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal interface AdminAccessClient {
    suspend fun status(): Api.AdminAccess
    suspend fun unlock(password: String): Api.AdminAccess
}

internal interface AdminServerClient {
    suspend fun activeDevices(): Api.ActiveDevices
}

@Composable
internal fun AdministrationSettings(
    modifier: Modifier = Modifier,
    client: AdminAccessClient? = null,
) {
    var page by rememberSaveable { mutableStateOf("menu") }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val uriHandler = LocalUriHandler.current
    BackHandler(page != "menu") { page = "menu" }
    Column(modifier) {
        if (page == "menu") {
            Column(
                Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                SettingsMenuItem("Про додаток", Icons.Default.Info) { page = "about" }
                SettingsMenuItem("Адміністрування", Icons.Default.AdminPanelSettings) {
                    page = "admin"
                }
                SettingsMenuItem("Політика конфіденційності", Icons.Default.Lock) {
                    uriHandler.openUri("https://api.bordersignal.pp.ua/privacy?v=20260924")
                }
            }
        } else if (page == "about") {
            SettingsPageHeader("Про додаток") { page = "menu" }
            AboutContent(Modifier.fillMaxWidth().weight(1f))
        } else {
            SettingsPageHeader("Адміністрування") { page = "menu" }
            TabRow(selectedTabIndex = tab, containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary) {
                listOf("Сервер", "Admin").forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = { tab = index },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        text = { Text(label, fontWeight = FontWeight.Bold) })
                }
            }
            if (tab == 0) {
                val server = remember {
                    object : AdminServerClient {
                        override suspend fun activeDevices() = Api.activeDevices()
                    }
                }
                AdminServerContent(server, Modifier.fillMaxWidth().weight(1f))
            } else {
                val application = LocalContext.current.applicationContext
                // The ID identifies this installation on the server.  It is not the
                // device secret and is intentionally shown only when an owner must
                // approve a replacement installation.
                val installationId = if (client == null) {
                    remember(application) { DeviceStore.credentials(application)?.deviceId }
                } else {
                    null
                }
                val access = client ?: remember(application) {
                    val installation = (application as AvelRenApp).installation
                    object : AdminAccessClient {
                        override suspend fun status() =
                            installation.authenticatedCall { Api.adminAccess(it) }
                        override suspend fun unlock(password: String) =
                            installation.authenticatedCall { Api.unlockAdmin(it, password) }
                    }
                }
                AdminAccessForm(access, installationId, Modifier.fillMaxWidth().weight(1f))
            }
        }
    }
}

@Composable
private fun SettingsMenuItem(label: String, icon: ImageVector, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Row(
        Modifier.fillMaxWidth().border(1.5.dp, SignWarn.copy(alpha = 0.5f), shape)
            .clickable(onClick = onClick).heightIn(min = 60.dp)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(icon, contentDescription = null, tint = SignWarn)
        Text(label, Modifier.weight(1f), fontWeight = FontWeight.Bold)
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null,
            tint = SignWarn)
    }
}

@Composable
private fun SettingsPageHeader(title: String, onBack: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад")
        }
        Text(title, style = MaterialTheme.typography.titleMedium)
    }
}

@Composable
private fun AboutContent(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val releaseNotes = remember(context) {
        context.assets.open("release-notes/v0.1.2.uk.txt")
            .bufferedReader(Charsets.UTF_8).use { it.readText().trimEnd() }
    }
    val previousNotes = remember(context) {
        context.assets.open("release-notes/v0.1.1.uk.txt")
            .bufferedReader(Charsets.UTF_8).use { it.readText().trimEnd() }
    }
    val earlierNotes = remember(context) {
        context.assets.open("release-notes/v0.1.0.uk.txt")
            .bufferedReader(Charsets.UTF_8).use { it.readText().trimEnd() }
    }
    Column(
        modifier.verticalScroll(rememberScrollState())
            .padding(start = 20.dp, top = 20.dp, end = 20.dp, bottom = 140.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("AvelRen — версія ${BuildConfig.VERSION_NAME}",
            style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("0.1.2", color = SignWarn, fontWeight = FontWeight.Bold)
        Text(releaseNotes)
        HorizontalDivider()
        Text("0.1.1", color = SignWarn, fontWeight = FontWeight.Bold)
        Text(previousNotes)
        HorizontalDivider()
        Text("0.1.0", color = SignWarn, fontWeight = FontWeight.Bold)
        Text(earlierNotes)
    }
}

@Composable
private fun AdminServerContent(server: AdminServerClient, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var count by remember { mutableStateOf<Int?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    suspend fun load() {
        busy = true
        error = null
        try {
            val result = server.activeDevices()
            count = result.active_devices
        } catch (e: CancellationException) {
            throw e
        } catch (e: ClientRequestException) {
            count = null
            error = when (e.response.status) {
                HttpStatusCode.NotFound -> "Показник ще не доступний на сервері."
                else -> "Не вдалося отримати кількість пристроїв."
            }
        } catch (_: Exception) {
            count = null
            error = "Не вдалося отримати кількість пристроїв."
        } finally {
            busy = false
        }
    }

    LaunchedEffect(Unit) { load() }
    Column(modifier.padding(vertical = 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically) {
            Text("Активні пристрої —", Modifier.weight(1f),
                style = MaterialTheme.typography.titleMedium, maxLines = 1,
                overflow = TextOverflow.Ellipsis)
            Text(count?.toString() ?: "…", style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold, maxLines = 1)
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (busy) CircularProgressIndicator(Modifier.size(24.dp))
        TextButton(onClick = { scope.launch { load() } }, enabled = !busy) {
            Text("Оновити")
        }
    }
}

@Composable
private fun AdminAccessForm(
    access: AdminAccessClient,
    installationId: String?,
    modifier: Modifier = Modifier,
) {
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
        } catch (e: ClientRequestException) {
            status = null
            error = if (e.response.status == HttpStatusCode.NotFound) {
                "Вхід Admin ще не доступний на сервері. Потрібне оновлення серверної частини."
            } else {
                "Сервер відхилив запит входу. Спробуйте пізніше."
            }
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
            "awaiting_approval" -> {
                Text("Ця інсталяція очікує підтвердження адміністратора.")
                if (installationId != null) {
                    Text("ID цієї інсталяції:", fontWeight = FontWeight.Bold)
                    SelectionContainer { Text(installationId) }
                    Text("Передайте цей ID власнику для звірки. Це не пароль і не секрет.")
                }
            }
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
