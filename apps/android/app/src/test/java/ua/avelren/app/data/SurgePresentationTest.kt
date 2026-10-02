package ua.avelren.app.data

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test
import ua.avelren.app.ui.SurgePresentation

class SurgePresentationTest {
    private val now = Instant.parse("2026-10-02T10:00:00Z")
    private val cp = SurgeCheckpoint(17, "Чоп", forecast_supported = true, fact_supported = true, data_fresh = true)
    @Test fun `forecast and fact use the exact approved separate phrases`() {
        val risk = SurgePresentation.cards(cp, SurgeStatus(17, "risk", expires_at = now.plusSeconds(60).toString()), now)
        assertEquals("Можливий початок масової реєстрації на Чопі", risk.forecast)
        assertFalse(risk.fact.contains("Почалось"))
        val fact = SurgePresentation.cards(cp, SurgeStatus(17, "started", expires_at = now.plusSeconds(60).toString()), now)
        assertEquals("Почалось зростання черги на Чопі", fact.fact)
        assertNotEquals(fact.forecast, fact.fact)
    }
    @Test fun `no signal does not claim no future surge`() {
        val cards = SurgePresentation.cards(cp, SurgeStatus(17, "no_signal"), now)
        assertTrue(cards.forecast.contains("сигналу"))
        assertFalse(cards.forecast.contains("напливу немає"))
    }
    @Test fun `broad window displays both dates in Kyiv`() {
        assertEquals("02.10 о 14:00 — 03.10 о 13:00 (Київ)", SurgePresentation.window(
            "2026-10-02T11:00:00Z", "2026-10-03T10:00:00Z"))
    }
    @Test fun `stale unsupported and future server status stay explicit`() {
        val cards = SurgePresentation.cards(cp, SurgeStatus(17, "unavailable", reason = "stale"), now)
        assertTrue(cards.forecast.contains("свіжих даних"))
        val unsupported = SurgePresentation.cards(cp.copy(forecast_supported = false), null, now)
        assertTrue(unsupported.forecast.contains("недоступний"))
        val expired = SurgePresentation.cards(cp, SurgeStatus(17, "risk", expires_at = now.minusSeconds(1).toString()), now)
        assertFalse(expired.forecast.contains("Можливий початок"))
    }
    @Test fun `voice needs notification permission and remains a user preference`() {
        assertTrue(SurgePresentation.voiceHint(true, false).contains("дозвіл"))
        assertTrue(SurgePresentation.voiceHint(false, true).contains("вимкнено"))
    }
    @Test fun `missing episode status does not imply no actual growth`() {
        val cards = SurgePresentation.cards(cp, null, now)
        assertFalse(cards.fact.contains("не зафіксовано"))
        assertTrue(cards.fact.contains("недоступний"))
    }

    @Test fun `missing Ukrainian voice is explained in phone UI`() {
        assertTrue(SurgePresentation.voiceHint(true, true, "uk_unavailable").contains("український голос"))
    }

}
