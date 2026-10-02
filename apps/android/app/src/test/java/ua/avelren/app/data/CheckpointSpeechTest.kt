package ua.avelren.app.data

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CheckpointSpeechTest {
    @Test fun all38QueuesKeepTheirDistinctApprovedNames() {
        val source = requireNotNull(javaClass.classLoader?.getResourceAsStream("checkpoint-speech.uk.json"))
        val rows = source.bufferedReader().use { Json.parseToJsonElement(it.readText()).jsonArray }
        assertEquals(38, rows.size)
        rows.forEach { element ->
            val row = element.jsonObject
            val id = row.getValue("id").jsonPrimitive.int
            val title = row.getValue("title").jsonPrimitive.content
            val place = row.getValue("location").jsonPrimitive.content
            assertEquals("КПП $id", place, CheckpointSpeech.location(id, title))
            assertEquals("Можливий початок масової реєстрації $place", CheckpointSpeech.message("surge_forecast", id, title))
            assertEquals("Почалось зростання черги $place", CheckpointSpeech.message("surge_started", id, title))
        }
    }
    @Test fun unknownCheckpointKeepsItsFullName() {
        assertEquals("на КПП «Новий КПП (спеціальна черга)»", CheckpointSpeech.location(999, "Новий КПП (спеціальна черга)"))
    }
    @Test fun categoryComesFromCurrentTitleRatherThanOldId() {
        assertEquals("на Ягодині для порожніх вантажівок", CheckpointSpeech.location(1, "Ягодин – Дорогуськ (для порожніх вантажівок ≥ 7,5 тонн)"))
        assertEquals("на Ягодині", CheckpointSpeech.location(29, "Ягодин – Дорогуськ (для вантажівок ≥ 7,5 тонн)"))
    }
    @Test(expected = IllegalArgumentException::class) fun unrelatedEventIsRejected() {
        CheckpointSpeech.message("eta", 17, "Чоп")
    }
}
