package ua.avelren.app.data

/**
 * Що саме заважає алерту дійти до користувача (AND-2).
 *
 * Секрет у тому, що «дозвіл на сповіщення» — не один прапорець. Алерт мовчки не
 * з'явиться щонайменше в трьох випадках: немає runtime-permission (Android 13+),
 * сповіщення застосунку вимкнені в системі, або заблокований саме канал
 * `avelren_alerts`. Для сервісу, весь сенс якого — розбудити водія, кожен із них
 * критичний, тож ведемо користувача в потрібне місце, а не показуємо одну
 * загальну помилку.
 */
sealed interface NotificationPermissionState {
    /** Усе гаразд: алерт реально з'явиться. */
    data object Granted : NotificationPermissionState

    /** Можна показати системний діалог запиту. */
    data object NeedsRequest : NotificationPermissionState

    /** Діалог більше не з'явиться — лише налаштування застосунку. */
    data object NeedsAppSettings : NotificationPermissionState

    /** Застосунок дозволений, але канал алертів вимкнений — ведемо в канал. */
    data object NeedsAlertChannelSettings : NotificationPermissionState
}

/**
 * Чиста логіка стану дозволу — без Android-залежностей, тож повністю тестована
 * на JVM. Викликач передає факти (SDK, permission, `areNotificationsEnabled()`,
 * importance каналу, `shouldShowRequestPermissionRationale`) і персистовану
 * історію.
 */
object NotificationPermission {

    /**
     * Персистована історія запитів. Одного `asked` замало: користувач може
     * змахнути діалог, не вибираючи нічого — тоді стан permission не
     * змінюється, і «asked без rationale» помилково виглядав би як permanent
     * denial. Тому явну відмову фіксуємо окремо.
     */
    data class History(
        val asked: Boolean = false,
        val deniedOnce: Boolean = false,
        val everGranted: Boolean = false,
    )

    /** З Android 13 показ сповіщень — runtime-permission POST_NOTIFICATIONS. */
    const val RUNTIME_PERMISSION_SDK = 33

    fun evaluate(
        sdkInt: Int,
        runtimeGranted: Boolean,
        appNotificationsEnabled: Boolean,
        alertChannelBlocked: Boolean,
        showRationale: Boolean,
        history: History,
    ): NotificationPermissionState {
        // 1. Runtime-permission (лише 33+). Без нього решта не має значення.
        if (sdkInt >= RUNTIME_PERMISSION_SDK && !runtimeGranted) {
            return when {
                // Дозвіл був і зник — діалогу вже не буде, тільки Settings.
                history.everGranted -> NotificationPermissionState.NeedsAppSettings
                // Ще не питали, або система готова показати діалог знову.
                !history.asked || showRationale -> NotificationPermissionState.NeedsRequest
                // Явно відмовляли, а rationale вже не пропонують → permanent.
                history.deniedOnce -> NotificationPermissionState.NeedsAppSettings
                // asked, але без явної відмови — це змах діалогу. Не караємо.
                else -> NotificationPermissionState.NeedsRequest
            }
        }

        // 2. Сповіщення застосунку вимкнені в системі. Стосується ВСІХ версій:
        //    на 8–12 runtime-permission немає, і без цієї перевірки застосунок
        //    вважав би, що все гаразд, тоді як пуші йдуть у порожнечу.
        if (!appNotificationsEnabled) return NotificationPermissionState.NeedsAppSettings

        // 3. Застосунок дозволений, але саме канал алертів заблокований
        //    (IMPORTANCE_NONE) — ведемо одразу в налаштування каналу.
        if (alertChannelBlocked) return NotificationPermissionState.NeedsAlertChannelSettings

        return NotificationPermissionState.Granted
    }

    /**
     * Фіксує факт **уже виданого** дозволу в історії.
     *
     * `everGranted` інакше пишеться лише в callback запиту — а він не спрацює
     * ніколи, якщо дозвіл видали до появи цього коду (оновлення APK поверх
     * установки, де все вже було дозволено) або через системні налаштування.
     * Тоді пізніший revoke виглядав би як «ще ніколи не питали» і вів у
     * NeedsRequest замість NeedsAppSettings — тобто саме той сценарій, який
     * AND-2 мав закрити, для наявних установок не працював би.
     *
     * Нижче API 33 `runtimeGranted` синтезується як `true` (runtime-permission
     * не існує), тож сідувати з нього не можна — це не доказ реального grant.
     *
     * Повертає ту саму історію, якщо змінювати нічого — викликач за цим
     * розуміє, що записувати в сховище не треба.
     */
    fun observeCurrentGrant(
        sdkInt: Int,
        runtimeGranted: Boolean,
        history: History,
    ): History =
        if (sdkInt >= RUNTIME_PERMISSION_SDK && runtimeGranted && !history.everGranted) {
            history.copy(everGranted = true)
        } else {
            history
        }

    /**
     * Одноразова міграція історії для установок, оновлених з версії ДО AND-2.
     *
     * Стара `MainActivity` безумовно викликала `launch(POST_NOTIFICATIONS)` на
     * кожному `onCreate`. Тому існуючий користувач, який до AND-2 вже відмовляв,
     * після оновлення APK має `runtimeGranted=false`, але нову AND-2 history —
     * порожню. `observeCurrentGrant()` тут нічого не сідує (дозвіл не granted), а
     * `evaluate()` без цієї міграції трактує `!asked` як `NeedsRequest`, після
     * чого `onCreate` знову смикає launcher — але системний діалог після
     * повторних Deny вже не з'явиться. Користувач застрягав би на кнопці
     * «Дозволити», яка фактично нічого не лікує.
     *
     * Розрізнення fresh install / upgrade передається ззовні (`isUpgrade`) —
     * викликач бере його з `PackageManager` (firstInstallTime != lastUpdateTime).
     * Fresh install лишаємо з порожньою історією → `NeedsRequest` і одноразовий
     * автозапит. Для upgrade з ПОРОЖНЬОЮ AND-2 history та `!runtimeGranted` на
     * API 33+ факт відмови гарантований (legacy-код точно питав), тож фіксуємо
     * `asked=true, deniedOnce=true`. Далі вже наявний short-circuit `showRationale`
     * у `evaluate()` сам розділяє відновлюваний single-denial (rationale=true →
     * `NeedsRequest`) і permanent denial (rationale=false → `NeedsAppSettings`).
     *
     * Виконується рівно раз (викликач тримає persisted marker). Якщо історія вже
     * НЕ порожня — AND-2 сам веде облік, чіпати нічого. Grant не сідуємо тут: це
     * робота `observeCurrentGrant()`.
     */
    fun migrateLegacyHistory(
        sdkInt: Int,
        isUpgrade: Boolean,
        runtimeGranted: Boolean,
        history: History,
    ): History = when {
        history != History() -> history          // AND-2 вже веде облік
        !isUpgrade -> history                     // fresh install — мігрувати нічого
        sdkInt < RUNTIME_PERMISSION_SDK -> history // немає runtime-permission
        runtimeGranted -> history                 // grant засідить observeCurrentGrant
        else -> History(asked = true, deniedOnce = true)
    }

    /**
     * Оновлення історії за результатом системного діалогу.
     *
     * `showRationaleNow` читається ПІСЛЯ результату — саме він відрізняє явну
     * відмову (rationale стає true) від змаху діалогу (стан не змінився, тож
     * rationale лишається false).
     */
    fun afterRequest(
        history: History,
        granted: Boolean,
        showRationaleNow: Boolean,
    ): History = history.copy(
        asked = true,
        deniedOnce = history.deniedOnce || (!granted && showRationaleNow),
        everGranted = history.everGranted || granted,
    )
}
