package ua.avelren.app.notify

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Tests of the pure reconciliation logic (A-02). The most fragile part is key
 * parsing and the set-diff; that is exactly what we verify on the JVM without instrumentation.
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
        val server = setOf(AlertKey("threshold", 6)) // 5 was closed by the server
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
        // 10_000_005 and 5 have the same display-id (% 10^7), but these are
        // DIFFERENT alerts. Via extras we store the full Long, so a server with {5}
        // does NOT confirm 10_000_005 → it is stale.
        val big = 10_000_005L
        val active = listOf(withKey(id = 10_000_005, kind = "threshold", alertId = big))
        val serverHasSmall = setOf(AlertKey("threshold", 5))
        assertEquals(
            listOf(10_000_005),
            AlertReconciliation.staleNotificationIds(active, serverHasSmall),
        )
        // But if the server has exactly the full id — not stale.
        val serverHasBig = setOf(AlertKey("threshold", big))
        assertTrue(AlertReconciliation.staleNotificationIds(active, serverHasBig).isEmpty())
    }

    @Test
    fun `health and unknown notifications are never touched`() {
        val active = listOf(
            noKey(id = 30_000_123), // health (kindCode=3), without extras
            noKey(id = 99_999_999), // an unknown namespace
        )
        // Even with an empty server set, health/unknown are not dismissed.
        assertTrue(AlertReconciliation.staleNotificationIds(active, emptySet()).isEmpty())
    }

    @Test
    fun `legacy notification without extras maps via truncated id`() {
        // A notification shown by an old version: no extras, only the display-id.
        val legacyId = 1 * AlertReconciliation.SPAN + 5 // threshold:5 (truncated)
        val active = listOf(noKey(legacyId))

        // The server confirms threshold:5 → not stale (comparison by the truncated id).
        val serverActive = setOf(AlertKey("threshold", 5))
        assertTrue(AlertReconciliation.staleNotificationIds(active, serverActive).isEmpty())

        // The server has nothing → the legacy one is stale too.
        assertEquals(
            listOf(legacyId),
            AlertReconciliation.staleNotificationIds(active, emptySet()),
        )
    }

    @Test
    fun `result never contains an id absent from the snapshot`() {
        // B2 regression: reconciliation works with a snapshot taken BEFORE the
        // request to the server. Even if the server set does not contain some
        // alert, only what is in the captured list can be dismissed. That is, a new
        // notification that arrived after the snapshot (not in `active`) cannot end
        // up in the result — an invariant of the function itself.
        val active = listOf(withKey(id = 10, kind = "threshold", alertId = 5))
        val server = emptySet<AlertKey>() // the server "has nothing"
        val stale = AlertReconciliation.staleNotificationIds(active, server)
        val activeIds = active.map { it.notificationId }.toSet()
        assertTrue(stale.all { it in activeIds })
        // Specifically: id 11 (a hypothetical new notification outside the snapshot) is not here.
        assertFalse(stale.contains(11))
    }

    @Test
    fun `fetch failure cancels nothing - fail-safe A-02 with null server set`() {
        // AND-1: the reconciler fetches active-alerts through InstallationRepository.
        // If the fetch/recovery failed, the server set = null (not empty), and no
        // local notification is dismissed — otherwise a network failure would
        // dismiss the real alarms.
        val active = listOf(
            withKey(id = 10, kind = "threshold", alertId = 5),
            withKey(id = 20, kind = "eta", alertId = 9),
        )
        assertTrue(AlertReconciliation.staleNotificationIdsOrNothing(active, null).isEmpty())
        // But a confirmed empty set (a 200 "there are none active") does dismiss.
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
        // health (kindCode=3) → null, reconciliation does not touch it.
        assertNull(AlertReconciliation.legacyKeyFromNotificationId(3 * AlertReconciliation.SPAN + 1))
    }
}
