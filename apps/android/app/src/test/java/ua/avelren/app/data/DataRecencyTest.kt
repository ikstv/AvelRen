package ua.avelren.app.data

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class DataRecencyTest {
    private val now = Instant.parse("2026-10-22T10:00:00Z")
    @Test fun `fresh response does not refresh old observation`() {
        val info = DataRecency.describe("2026-10-22T09:55:59Z", now, InternetState.ONLINE, true)
        assertTrue(info.attention)
        assertEquals("Дані застаріли", info.title)
        assertTrue(info.detail.contains("4 хв тому"))
    }
    @Test fun `offline retains measurement time but never claims current data`() {
        val info = DataRecency.describe(now.toString(), now, InternetState.OFFLINE, true)
        assertTrue(info.attention)
        assertTrue(info.title.contains("Немає інтернету"))
        assertTrue(info.detail.contains("13:00:00"))
    }
    @Test fun `invalid missing and future timestamps are unknown`() {
        listOf(null, "bad", now.plusSeconds(61).toString()).forEach {
            assertEquals("Актуальність даних невідома", DataRecency.describe(it, now, InternetState.ONLINE, true).title)
        }
    }
    @Test fun `three collection cycles are the freshness boundary`() {
        assertFalse(DataRecency.describe(now.minusSeconds(180).toString(), now, InternetState.ONLINE, true).attention)
        assertTrue(DataRecency.describe(now.minusSeconds(181).toString(), now, InternetState.ONLINE, true).attention)
    }
    @Test fun `network failure does not label recent cached measurement current`() {
        assertTrue(DataRecency.describe(now.toString(), now, InternetState.ONLINE, false).attention)
        assertEquals("Перевіряємо оновлення", DataRecency.describe(now.toString(), now, InternetState.UNKNOWN, null).title)
    }
}
