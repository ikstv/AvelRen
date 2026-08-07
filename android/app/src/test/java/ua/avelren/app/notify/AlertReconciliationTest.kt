package ua.avelren.app.notify

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Тести чистої reconciliation-логіки (A-02). Найкрихкіша частина — розбір
 * ключів і set-diff; саме її й перевіряємо на JVM без інструментації.
 */
class AlertReconciliationTest {

    private fun withKey(id: Int, kind: String, alertId: Long) =
        ActiveNotification(id, AlertKey(kind, alertId))

    private fun noKey(id: Int) = ActiveNotification(id, null)

    @Test
    fun `threshold and eta with same numeric id are distinct keys`() {
        assertFalse(AlertKey("threshold", 5) == AlertKey("eta", 5))
    }

    @Test
    fun `notification not in server pending is stale`() {
        val active = listOf(
            withKey(id = 10, kind = "threshold", alertId = 5),
            withKey(id = 11, kind = "threshold", alertId = 6),
        )
        val server = setOf(AlertKey("threshold", 6)) // 5 закритий сервером
        val stale = AlertReconciliation.staleNotificationIds(active, server)
        assertEquals(listOf(10), stale)
    }

    @Test
    fun `empty server set marks all alert-backed notifications stale`() {
        val active = listOf(
            withKey(id = 10, kind = "threshold", alertId = 5),
            withKey(id = 20, kind = "eta", alertId = 9),
        )
        val stale = AlertReconciliation.staleNotificationIds(active, emptySet())
        assertEquals(listOf(10, 20), stale)
    }

    @Test
    fun `full long alert id is preserved without truncation`() {
        // 10_000_005 і 5 мають однаковий display-id (% 10^7), але це РІЗНІ
        // alert'и. Через extras ми зберігаємо повний Long, тож сервер із {5}
        // НЕ підтверджує 10_000_005 → воно stale.
        val big = 10_000_005L
        val active = listOf(withKey(id = 10_000_005, kind = "threshold", alertId = big))
        val serverHasSmall = setOf(AlertKey("threshold", 5))
        assertEquals(
            listOf(10_000_005),
            AlertReconciliation.staleNotificationIds(active, serverHasSmall),
        )
        // А якщо сервер має саме повний id — не stale.
        val serverHasBig = setOf(AlertKey("threshold", big))
        assertTrue(AlertReconciliation.staleNotificationIds(active, serverHasBig).isEmpty())
    }

    @Test
    fun `health and unknown notifications are never touched`() {
        val active = listOf(
            noKey(id = 30_000_123), // health (kindCode=3), без extras
            noKey(id = 99_999_999), // невідомий namespace
        )
        // Навіть за порожнього server-набору health/unknown не гасяться.
        assertTrue(AlertReconciliation.staleNotificationIds(active, emptySet()).isEmpty())
    }

    @Test
    fun `legacy notification without extras maps via truncated id`() {
        // Сповіщення показане старою версією: extras немає, лише display-id.
        val legacyId = 1 * AlertReconciliation.SPAN + 5 // threshold:5 (усічено)
        val active = listOf(noKey(legacyId))

        // Сервер підтверджує threshold:5 → не stale (порівняння за усіченим).
        val serverActive = setOf(AlertKey("threshold", 5))
        assertTrue(AlertReconciliation.staleNotificationIds(active, serverActive).isEmpty())

        // Сервер нічого не має → legacy теж stale.
        assertEquals(
            listOf(legacyId),
            AlertReconciliation.staleNotificationIds(active, emptySet()),
        )
    }

    @Test
    fun `result never contains an id absent from the snapshot`() {
        // B2-регресія: reconciliation працює зі знімком, зробленим ДО запиту
        // до сервера. Навіть якщо server-набір не містить якогось alert'а,
        // погасити можна лише те, що є у знятому списку. Тобто нова
        // нотифікація, яка прийшла вже після знімка (її немає у `active`),
        // не може опинитися в результаті — інваріант самої функції.
        val active = listOf(withKey(id = 10, kind = "threshold", alertId = 5))
        val server = emptySet<AlertKey>() // сервер «нічого не має»
        val stale = AlertReconciliation.staleNotificationIds(active, server)
        val activeIds = active.map { it.notificationId }.toSet()
        assertTrue(stale.all { it in activeIds })
        // Конкретно: id 11 (гіпотетична нова нотифікація поза знімком) не тут.
        assertFalse(stale.contains(11))
    }

    @Test
    fun `fetch failure cancels nothing - fail-safe A-02 with null server set`() {
        // AND-1: reconciler дістає active-alerts через InstallationRepository.
        // Якщо fetch/recovery впав, серверний набір = null (а не порожній), і
        // жодне локальне сповіщення не гаситься — інакше мережевий збій погасив
        // би справжні тривоги.
        val active = listOf(
            withKey(id = 10, kind = "threshold", alertId = 5),
            withKey(id = 20, kind = "eta", alertId = 9),
        )
        assertTrue(AlertReconciliation.staleNotificationIdsOrNothing(active, null).isEmpty())
        // А підтверджений порожній набір (200 «активних нема») — таки гасить.
        assertEquals(
            listOf(10, 20),
            AlertReconciliation.staleNotificationIdsOrNothing(active, emptySet()),
        )
    }

    @Test
    fun `legacy key parsing recognizes kinds and skips health`() {
        assertEquals(
            AlertKey("threshold", 42),
            AlertReconciliation.legacyKeyFromNotificationId(1 * AlertReconciliation.SPAN + 42),
        )
        assertEquals(
            AlertKey("eta", 7),
            AlertReconciliation.legacyKeyFromNotificationId(2 * AlertReconciliation.SPAN + 7),
        )
        // health (kindCode=3) → null, reconciliation його не чіпає.
        assertNull(AlertReconciliation.legacyKeyFromNotificationId(3 * AlertReconciliation.SPAN + 1))
    }
}
