package ua.avelren.app.notify

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.*
import org.junit.Test

class VoiceAssetPolicyTest {
    // Rejecting invalid resource names prevents access outside the ready catalogue.
    @Test fun acceptsOnlyCanonicalPositiveCheckpointAndKnownKind() {
        assertEquals(VoiceSoundKey(17, "surge_forecast"), VoiceAssetPolicy.parsePath("/v1/17/surge_forecast.wav"))
        assertEquals(VoiceSoundKey(29, "surge_started"), VoiceAssetPolicy.parsePath("/v1/29/surge_started.wav"))
        listOf("/v1/../surge_forecast.wav", "/v1/0/surge_forecast.wav", "/v1/-1/surge_started.wav",
            "/v1/017/surge_started.wav", "/v1/17/other.wav", "/v1/17/surge_started.wav/extra",
            "/v1/2147483648/surge_started.wav", "/v1/%31%37/surge_started.wav").forEach {
            assertNull(it, VoiceAssetPolicy.parsePath(it))
        }
    }
    @Test fun derivesDurationFromPcmNotFileSize() {
        assertEquals(WavInfo(1000), VoiceAssetPolicy.inspectWav(wav(48_000)))
        assertEquals(WavInfo(15_000), VoiceAssetPolicy.inspectWav(wav(720_000)))
    }
    @Test fun rejectsTruncatedChunksEmptyAudioAndLongSpeech() {
        listOf(byteArrayOf(1, 2, 3), wav(0), wav(720_002), wav(48_000).copyOf(100),
            wav(48_000).apply { this[40] = 0x7f },
            wav(48_000).apply { this[20] = 3 },
            wav(48_000).apply { this[28] = 0 },
            wav(48_000).apply { this[32] = 4 }).forEach { assertNull(VoiceAssetPolicy.inspectWav(it)) }
    }
    private fun wav(size: Int): ByteArray = ByteBuffer.allocate(44 + size).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray()); putInt(36 + size); put("WAVEfmt ".toByteArray()); putInt(16)
        putShort(1); putShort(1); putInt(24_000); putInt(48_000); putShort(2); putShort(16)
        put("data".toByteArray()); putInt(size)
    }.array()
}
