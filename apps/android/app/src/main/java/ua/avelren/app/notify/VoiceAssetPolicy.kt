package ua.avelren.app.notify

@kotlinx.serialization.Serializable
data class VoiceSoundKey(val checkpointId: Int, val kind: String)
data class WavInfo(val durationMs: Long)

object VoiceAssetPolicy {
    private val pathPattern = Regex("/v1/([1-9][0-9]*)/(surge_forecast|surge_started)\\.wav")
    fun parsePath(path: String): VoiceSoundKey? {
        val match = pathPattern.matchEntire(path) ?: return null
        val id = match.groupValues[1].toIntOrNull() ?: return null
        return VoiceSoundKey(id, match.groupValues[2])
    }
    fun inspectWav(bytes: ByteArray): WavInfo? {
        fun text(offset: Int) = String(bytes, offset, 4, Charsets.US_ASCII)
        fun uint(offset: Int): Long = (0..3).fold(0L) { n, i -> n or ((bytes[offset + i].toLong() and 255) shl (8 * i)) }
        fun ushort(offset: Int): Int = (bytes[offset].toInt() and 255) or ((bytes[offset + 1].toInt() and 255) shl 8)
        if (bytes.size < 44 || text(0) != "RIFF" || text(8) != "WAVE" || uint(4) + 8 != bytes.size.toLong()) return null
        var offset = 12
        var rate = 0L
        var alignment = 0
        var data = 0L
        var formatSeen = false
        var dataSeen = false
        while (offset <= bytes.size - 8) {
            val size = uint(offset + 4)
            val start = offset + 8
            if (size > bytes.size - start) return null
            when (text(offset)) {
                "fmt " -> {
                    if (formatSeen || size < 16 || ushort(start) != 1) return null
                    formatSeen = true
                    val channels = ushort(start + 2)
                    val sampleRate = uint(start + 4)
                    rate = uint(start + 8)
                    alignment = ushort(start + 12)
                    val bits = ushort(start + 14)
                    if (channels !in 1..2 || sampleRate !in 8_000..192_000 || bits !in listOf(8, 16, 24, 32) ||
                        alignment != channels * bits / 8 || rate != sampleRate * alignment) return null
                }
                "data" -> {
                    if (dataSeen || !formatSeen || size == 0L || size % alignment != 0L) return null
                    dataSeen = true
                    data = size
                }
            }
            val next = start.toLong() + size + size % 2
            if (next > bytes.size) return null
            offset = next.toInt()
        }
        if (offset != bytes.size || !dataSeen || rate == 0L || data * 1000 > rate * 15_000) return null
        val duration = (data * 1000 + rate - 1) / rate
        return if (duration > 0) WavInfo(duration) else null
    }
}
