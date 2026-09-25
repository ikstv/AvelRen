package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant

class ServerBadgeTest {
    private val now = Instant.parse("2026-09-25T18:40:00Z")
    private val future = Instant.parse("2026-09-25T18:42:00Z")

    @Test fun `confirmed maintenance is shown while server answers`() {
        assertEquals(ServerBadge.MAINTENANCE, serverBadge(false, false, future, now))
    }

    @Test fun `confirmed maintenance becomes restart while api is unavailable`() {
        assertEquals(ServerBadge.RESTARTING, serverBadge(true, false, future, now))
    }

    @Test fun `unconfirmed api failure remains offline`() {
        assertEquals(ServerBadge.OFFLINE, serverBadge(true, false, null, now))
    }

    @Test fun `expired window cannot disguise an outage`() {
        assertEquals(ServerBadge.OFFLINE, serverBadge(true, false, now, now))
    }

    @Test fun `invalid server timestamp is rejected`() {
        assertNull(activeMaintenanceEnd("not-a-date", now))
    }
}
