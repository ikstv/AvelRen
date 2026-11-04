package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import ua.avelren.app.ui.theme.hapticClickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.graphics.vector.ImageVector
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
import ua.avelren.app.ui.theme.AppAccent as SignWarn
import ua.avelren.app.ui.theme.ThemeChoice
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.data.UiPrefs
import androidx.compose.material.icons.filled.Palette
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

internal interface AdminAccessClient {
    suspend fun status(): Api.AdminAccess
    suspend fun unlock(password: String): Api.AdminAccess
}

internal interface AdminServerClient {
    suspend fun serverCpuStatus(): Api.ServerCpuStatus
}

@Composable
internal fun AdministrationSettings(
    modifier: Modifier = Modifier,
    client: AdminAccessClient? = null,
    serverClient: AdminServerClient? = null,
    onOpenPrivacyPolicy: (() -> Unit)? = null,
    initialPage: String = "menu",
    onPageChanged: ((String) -> Unit)? = null,
    menuContent: (@Composable ((String) -> Unit) -> Unit)? = null,
) {
    var page by rememberSaveable(initialPage) { mutableStateOf(initialPage) }
    LaunchedEffect(page) { onPageChanged?.invoke(page) }
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val uriHandler = LocalUriHandler.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val selectedTheme = LocalThemeChoice.current
    BackHandler(page != "menu") { page = "menu" }
    Column(modifier) {
        if (page == "menu") {
            if (menuContent != null) {
                menuContent { page = it }
            } else {
            Column(
                Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                SettingsMenuItem("Про додаток", Icons.Default.Info) { page = "about" }
                SettingsMenuItem("Тема", Icons.Default.Palette) { page = "theme" }
                SettingsMenuItem("Для розробника", Icons.Default.AdminPanelSettings) {
                    page = "admin"
                }
            }
            }
        } else if (page == "theme") {
            SettingsPageHeader("Тема") { page = "menu" }
            Column(if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.fillMaxWidth().weight(1f)
                .verticalScroll(rememberScrollState()).padding(vertical = 16.dp)
                else Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                listOf(ThemeChoice.DARK to "Темна (за замовчуванням)", ThemeChoice.LIGHT to "Світла").forEach { (choice, label) ->
                    Row(
                        Modifier.fillMaxWidth().then(if (BuildConfig.ENABLE_TEST_DRAWER) Modifier
                            .clip(RoundedCornerShape(20.dp)).background(MaterialTheme.colorScheme.surfaceVariant)
                            .border(1.dp, if (choice == selectedTheme) SignWarn else MaterialTheme.avelren.line,
                                RoundedCornerShape(20.dp))
                            else Modifier.border(1.5.dp, SignWarn.copy(alpha = 0.5f), RoundedCornerShape(16.dp)))
                            .hapticClickable { scope.launch { UiPrefs.setTheme(context, choice) } }.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = choice == selectedTheme,
                            onClick = ua.avelren.app.ui.theme.hapticClick { scope.launch { UiPrefs.setTheme(context, choice) } })
                        Column((if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.weight(1f) else Modifier).padding(start = 12.dp)) {
                            Text(label, fontWeight = FontWeight.Bold)
                            Text(if (choice == ThemeChoice.DARK) "Чорна з жовтим" else "Світла з червоним",
                                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        } else if (page == "about") {
            SettingsPageHeader("Про додаток") { page = "menu" }
            // The policy remains a browser action; returning keeps the About tab active.
            TabRow(selectedTabIndex = 0, containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary) {
                Tab(selected = true, onClick = {},
                    text = { Text("Про додаток", fontWeight = FontWeight.Bold) })
                Tab(selected = false, onClick = ua.avelren.app.ui.theme.hapticClick {
                    if (onOpenPrivacyPolicy != null) onOpenPrivacyPolicy()
                    else uriHandler.openUri("https://api.bordersignal.pp.ua/privacy?v=20260924")
                }, text = { Text("Політика конфіденційності", fontWeight = FontWeight.Bold) })
            }
            AboutContent(Modifier.fillMaxWidth().weight(1f))
        } else {
            SettingsPageHeader("Для розробника") { page = "menu" }
            TabRow(selectedTabIndex = tab, containerColor = MaterialTheme.colorScheme.surface,
                contentColor = MaterialTheme.colorScheme.primary) {
                listOf("Сервер", "Admin").forEachIndexed { index, label ->
                    Tab(selected = tab == index, onClick = ua.avelren.app.ui.theme.hapticClick { tab = index },
                        selectedContentColor = MaterialTheme.colorScheme.primary,
                        unselectedContentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        text = { Text(label, fontWeight = FontWeight.Bold) })
                }
            }
            if (tab == 0) {
                val server = serverClient ?: remember {
                    object : AdminServerClient {
                        override suspend fun serverCpuStatus() = Api.serverCpuStatus()
                    }
                }
                ServerStatusContent(server, Modifier.fillMaxWidth().weight(1f))
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
                AdminAccessForm(access, installationId, Modifier.fillMaxWidth()
                    .weight(1f, fill = !BuildConfig.ENABLE_TEST_DRAWER))
            }
        }
    }
}

@Composable
private fun SettingsMenuItem(label: String, icon: ImageVector, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Row(
        Modifier.fillMaxWidth().border(1.5.dp, SignWarn.copy(alpha = 0.5f), shape)
            .hapticClickable(onClick = onClick).heightIn(min = 60.dp)
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
    Row(modifier = if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.fillMaxWidth().padding(vertical = 12.dp) else Modifier,
        verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = ua.avelren.app.ui.theme.hapticClick(onBack),
            modifier = if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.size(48.dp).clip(CircleShape)
                .background(MaterialTheme.colorScheme.surfaceVariant) else Modifier) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Назад",
                tint = if (BuildConfig.ENABLE_TEST_DRAWER) SignWarn else LocalContentColor.current)
        }
        Text(title, modifier = if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.weight(1f).padding(start = 12.dp) else Modifier,
            style = if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium,
            fontWeight = if (BuildConfig.ENABLE_TEST_DRAWER) FontWeight.Bold else null)
    }
}

@Composable
private fun AboutContent(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val candidateNotes = remember(context) {
        context.assets.open("release-notes/v0.1.4.uk.txt")
            .bufferedReader(Charsets.UTF_8).use { it.readText().trimEnd() }
    }
    val currentNotes = remember(context) {
        context.assets.open("release-notes/v0.1.3.uk.txt")
            .bufferedReader(Charsets.UTF_8).use { it.readText().trimEnd() }
    }
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
            .padding(if (BuildConfig.ENABLE_TEST_DRAWER) PaddingValues(vertical = 16.dp)
                else PaddingValues(start = 20.dp, top = 20.dp, end = 20.dp, bottom = 140.dp)),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("AvelRen — версія ${BuildConfig.VERSION_NAME}",
            style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        ReleaseNotesSection("Версія 0.1.4", candidateNotes)
        ReleaseNotesSection(releaseHistoryHeading("0.1.3", Instant.parse("2026-10-07T00:00:00Z")), currentNotes)
        // publishedAt відповідних GitHub Releases, звірено 07.10.2026.
        ReleaseNotesSection(releaseHistoryHeading("0.1.2", Instant.parse("2026-09-26T01:16:12Z")), releaseNotes)
        ReleaseNotesSection(releaseHistoryHeading("0.1.1", Instant.parse("2026-09-24T18:56:49Z")), previousNotes)
        ReleaseNotesSection(releaseHistoryHeading("0.1.0", Instant.parse("2026-09-24T11:05:47Z")), earlierNotes, divider = false)
    }
}

@Composable
private fun ReleaseNotesSection(heading: String, notes: String, divider: Boolean = true) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        Column(Modifier.fillMaxWidth().administrationPanel(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(heading, color = SignWarn, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(notes, color = AppInk, style = MaterialTheme.typography.bodyLarge)
        }
    } else {
        Text(heading, color = SignWarn, fontWeight = FontWeight.Bold)
        Text(notes)
        if (divider) HorizontalDivider()
    }
}

@Composable
private fun Modifier.administrationPanel(): Modifier {
    if (!BuildConfig.ENABLE_TEST_DRAWER) return this
    val shape = RoundedCornerShape(20.dp)
    return clip(shape).background(MaterialTheme.colorScheme.surfaceVariant)
        .border(1.dp, MaterialTheme.avelren.line, shape).padding(16.dp)
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
        modifier.verticalScroll(rememberScrollState()).imePadding().padding(vertical = 20.dp).administrationPanel(),
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
                        if (isAllowedAdminPinInput(value)) pin = value
                    },
                    label = { Text("Введіть пароль") },
                    shape = RoundedCornerShape(if (BuildConfig.ENABLE_TEST_DRAWER) 16.dp else 8.dp),
                    singleLine = true,
                    enabled = !busy,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (current.state == "invalid_pin") {
                    Text("Неправильний пароль. Залишилося спроб: ${current.attempts_remaining}.")
                }
                Button(
                    shape = RoundedCornerShape(if (BuildConfig.ENABLE_TEST_DRAWER) 16.dp else 12.dp),
                    enabled = !busy && isValidAdminPin(pin),
                    onClick = ua.avelren.app.ui.theme.hapticClick {
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
            TextButton(onClick = ua.avelren.app.ui.theme.hapticClick { scope.launch { load() } },
                modifier = if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.heightIn(min = 48.dp) else Modifier) { Text("Оновити стан") }
        }
    }
}
