package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Test
import ua.avelren.app.data.NotificationPermission.History
import ua.avelren.app.data.NotificationPermissionState as S

/**
 * Чиста логіка стану дозволу на сповіщення (AND-2).
 *
 * Перевіряємо не лише Android 13 runtime-permission, а весь шлях, яким алерт
 * може мовчки не дійти: app-wide блокування сповіщень і заблокований канал
 * `avelren_alerts` (IMPORTANCE_NONE).
 */
class NotificationPermissionTest {

    private fun eval(
        sdk: Int = 33,
        runtimeGranted: Boolean = true,
        appEnabled: Boolean = true,
        channelBlocked: Boolean = false,
        rationale: Boolean = false,
        asked: Boolean = false,
        deniedOnce: Boolean = false,
        everGranted: Boolean = false,
    ) = NotificationPermission.evaluate(
        sdkInt = sdk,
        runtimeGranted = runtimeGranted,
        appNotificationsEnabled = appEnabled,
        alertChannelBlocked = channelBlocked,
        showRationale = rationale,
        history = History(asked = asked, deniedOnce = deniedOnce, everGranted = everGranted),
    )

    // --- runtime permission (API 33+) -------------------------------------

    @Test
    fun `granted runtime with everything enabled is Granted`() {
        assertEquals(S.Granted, eval(runtimeGranted = true))
    }

    @Test
    fun `not granted and never asked needs request`() {
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = false))
    }

    @Test
    fun `not granted with rationale needs request`() {
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = true, rationale = true))
    }

    @Test
    fun `denied once without rationale needs app settings`() {
        // Повторна/permanent denial — діалог більше не з'явиться.
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, deniedOnce = true, rationale = false),
        )
    }

    @Test
    fun `dialog swiped away is not punished with settings`() {
        // asked=true, але користувач не натискав Deny (deniedOnce=false) і
        // rationale=false — це swipe-away, дозволено перепитати.
        assertEquals(
            S.NeedsRequest,
            eval(runtimeGranted = false, asked = true, deniedOnce = false, rationale = false),
        )
    }

    @Test
    fun `revoked after grant needs app settings`() {
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, everGranted = true, rationale = false),
        )
    }

    // --- app-wide вимкнення (усі API) -------------------------------------

    @Test
    fun `app notifications blocked below api 33 needs app settings`() {
        assertEquals(
            S.NeedsAppSettings,
            eval(sdk = 30, runtimeGranted = true, appEnabled = false),
        )
    }

    @Test
    fun `below api 33 with notifications enabled is Granted`() {
        assertEquals(S.Granted, eval(sdk = 30, runtimeGranted = false, appEnabled = true))
    }

    @Test
    fun `app notifications blocked outranks granted runtime permission`() {
        assertEquals(S.NeedsAppSettings, eval(runtimeGranted = true, appEnabled = false))
    }

    // --- заблокований канал -----------------------------------------------

    @Test
    fun `blocked alert channel needs channel settings`() {
        assertEquals(
            S.NeedsAlertChannelSettings,
            eval(runtimeGranted = true, appEnabled = true, channelBlocked = true),
        )
    }

    @Test
    fun `blocked alert channel below api 33 needs channel settings`() {
        assertEquals(
            S.NeedsAlertChannelSettings,
            eval(sdk = 30, runtimeGranted = false, appEnabled = true, channelBlocked = true),
        )
    }

    @Test
    fun `app-wide block takes precedence over channel block`() {
        // Немає сенсу вести в канал, якщо весь застосунок заблокований.
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = true, appEnabled = false, channelBlocked = true),
        )
    }

    // --- повернення з Settings --------------------------------------------

    @Test
    fun `returning from settings with everything enabled is Granted`() {
        assertEquals(
            S.Granted,
            eval(
                runtimeGranted = true, appEnabled = true, channelBlocked = false,
                asked = true, deniedOnce = true, everGranted = true,
            ),
        )
    }

    // --- міграція вже виданого дозволу (upgrade-установка) ----------------

    @Test
    fun `existing install with granted permission seeds everGranted`() {
        // Історія стартує порожньою після оновлення APK поверх установки, де
        // дозвіл уже був виданий: callback запиту не спрацює ніколи, тож факт
        // grant треба зафіксувати з фактичного стану.
        val fresh = History()
        assertEquals(
            History(asked = false, deniedOnce = false, everGranted = true),
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = true, history = fresh),
        )
    }

    @Test
    fun `existing grant then revoke needs app settings`() {
        // Наскрізний сценарій, заради якого потрібен seeding.
        val seeded = NotificationPermission.observeCurrentGrant(33, true, History())
        val afterRevoke = NotificationPermission.evaluate(
            sdkInt = 33,
            runtimeGranted = false,          // відкликали в Settings
            appNotificationsEnabled = true,
            alertChannelBlocked = false,
            showRationale = false,
            history = seeded,
        )
        assertEquals(S.NeedsAppSettings, afterRevoke)  // а не NeedsRequest
    }

    @Test
    fun `grant in settings after deny seeds everGranted`() {
        val denied = History(asked = true, deniedOnce = true, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = true),
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = true, history = denied),
        )
    }

    @Test
    fun `no seeding below api 33`() {
        // Нижче 33 runtimeGranted синтезується як true (runtime-permission не
        // існує) — це НЕ доказ реального grant, сідувати з нього не можна.
        val fresh = History()
        assertEquals(
            fresh,
            NotificationPermission.observeCurrentGrant(30, runtimeGranted = true, history = fresh),
        )
    }

    @Test
    fun `no seeding when not granted`() {
        val fresh = History()
        assertEquals(
            fresh,
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = false, history = fresh),
        )
    }

    // --- legacy-міграція (upgrade з версії до AND-2) ----------------------

    @Test
    fun `legacy permanent denial upgrade migrates to denied and needs app settings`() {
        // Оновлення з версії, де стара MainActivity питала на кожен старт;
        // користувач уже двічі відмовив → діалогу більше не буде.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = History(),
        )
        assertEquals(History(asked = true, deniedOnce = true, everGranted = false), migrated)
        // rationale=false бо система вже не показує діалог → ведемо в Settings,
        // а не залишаємо мертву кнопку «Дозволити».
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, deniedOnce = true, rationale = false),
        )
    }

    @Test
    fun `legacy single denial upgrade with rationale stays requestable`() {
        // Та сама міграція, але система ще готова показати діалог (одна відмова):
        // short-circuit showRationale у evaluate лишає NeedsRequest.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = History(),
        )
        assertEquals(
            S.NeedsRequest,
            eval(
                runtimeGranted = false,
                asked = migrated.asked, deniedOnce = migrated.deniedOnce, rationale = true,
            ),
        )
    }

    @Test
    fun `fresh install never asked is not migrated`() {
        // firstInstallTime == lastUpdateTime → isUpgrade=false: історія лишається
        // порожньою, evaluate дає NeedsRequest, onCreate робить один автозапит.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = false, runtimeGranted = false, history = History(),
        )
        assertEquals(History(), migrated)
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = false))
    }

    @Test
    fun `fresh install swipe away is not turned into denial`() {
        // Свайп на fresh install робить історію непорожньою (asked=true) ще ДО
        // будь-якої міграції — тож migrate лишає її незмінною, а не карає Settings.
        val swiped = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            swiped,
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = swiped,
            ),
        )
        assertEquals(
            S.NeedsRequest,
            eval(runtimeGranted = false, asked = true, deniedOnce = false, rationale = false),
        )
    }

    @Test
    fun `upgrade with granted permission is left for seeding`() {
        // Grant міграція не чіпає — це робота observeCurrentGrant.
        assertEquals(
            History(),
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = true, history = History(),
            ),
        )
    }

    @Test
    fun `no legacy migration below api 33`() {
        assertEquals(
            History(),
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 30, isUpgrade = true, runtimeGranted = false, history = History(),
            ),
        )
    }

    @Test
    fun `no legacy migration when history already tracked`() {
        // AND-2 вже щось записав (напр. everGranted після grant) — не перетирати.
        val tracked = History(asked = true, deniedOnce = false, everGranted = true)
        assertEquals(
            tracked,
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = tracked,
            ),
        )
    }

    // --- запис історії ----------------------------------------------------

    @Test
    fun `explicit deny is recorded as deniedOnce`() {
        // Явний «Don't allow» робить rationale=true одразу після результату.
        val h = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = false),
            NotificationPermission.afterRequest(h, granted = false, showRationaleNow = true),
        )
    }

    @Test
    fun `swiped away dialog is not recorded as denial`() {
        // Змах не змінює стан permission: rationale лишається false — це НЕ
        // відмова, інакше перший же змах відправив би користувача в Settings.
        val h = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = false, everGranted = false),
            NotificationPermission.afterRequest(h, granted = false, showRationaleNow = false),
        )
    }

    @Test
    fun `history records grant as everGranted`() {
        val h = History(asked = true, deniedOnce = true, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = true),
            NotificationPermission.afterRequest(h, granted = true, showRationaleNow = false),
        )
    }
}
