package com.lits.tts.sdk.internal

/** Preserve explicit line endings as punctuation before TN removes control characters. */
internal object TtsLineBreaks {
    private val lineBreaks = Regex("[ \\t]*[\\r\\n\\u2028\\u2029]+[ \\t\\r\\n\\u2028\\u2029]*")
    private const val punctuation = ".。!！?？,，;；:：、…"
    private const val closingDelimiters = "\"'”’)]}》】」』"

    fun normalize(text: String): String {
        val output = StringBuilder()
        var start = 0
        for (match in lineBreaks.findAll(text)) {
            output.append(text, start, match.range.first)
            var end = output.lastIndex
            while (end >= 0 && output[end] in closingDelimiters) end -= 1
            if (end >= 0 && !output[end].isWhitespace() && output[end] !in punctuation) {
                // Use the existing period token in both Chinese and English modes.
                output.insert(end + 1, '.')
            }
            if (output.isNotEmpty() && output.last() != ' ') output.append(' ')
            start = match.range.last + 1
        }
        if (start == 0) return text
        return output.append(text, start, text.length).toString()
    }
}
