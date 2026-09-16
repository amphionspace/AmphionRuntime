package com.lits.tts.sdk.internal

/** Cardinal readings shared by pre-native TN and already-normalized frontend input. */
internal object MandarinCardinal {
    private const val DIGITS = "零一二三四五六七八九"
    private val GROUP_UNITS = listOf("", "万", "亿", "万亿", "亿亿")
    private val SMALL_UNITS = listOf("", "十", "百", "千")

    fun read(text: String): String? {
        if (text.isEmpty() || text.any { it !in '0'..'9' }) return null
        var value = text.toLongOrNull() ?: return null
        if (value == 0L) return "零"
        val groups = mutableListOf<Int>()
        while (value > 0) {
            groups += (value % 10000).toInt()
            value /= 10000
        }
        val output = StringBuilder()
        var omittedGroup = false
        for (index in groups.indices.reversed()) {
            val group = groups[index]
            if (group == 0) {
                if (output.isNotEmpty()) omittedGroup = true
                continue
            }
            if (output.isNotEmpty() && (omittedGroup || group < 1000)) output.append('零')
            appendGroup(output, group, omitLeadingOne = output.isEmpty())
            output.append(GROUP_UNITS[index])
            omittedGroup = false
        }
        return output.toString()
    }

    private fun appendGroup(output: StringBuilder, value: Int, omitLeadingOne: Boolean) {
        var divisor = 1000
        var started = false
        var zero = false
        for (position in 3 downTo 0) {
            val digit = value / divisor % 10
            divisor /= 10
            if (digit == 0) {
                if (started) zero = true
                continue
            }
            if (zero) { output.append('零'); zero = false }
            if (!(position == 1 && digit == 1 && !started && omitLeadingOne)) output.append(DIGITS[digit])
            output.append(SMALL_UNITS[position])
            started = true
        }
    }
}
