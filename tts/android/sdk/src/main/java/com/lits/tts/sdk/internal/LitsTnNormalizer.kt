package com.lits.tts.sdk.internal

import android.util.Log
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.File
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

internal object LitsTnNormalizer {
    private val normalizersByRoot = ConcurrentHashMap<String, LayoutNormalizer>()

    fun normalize(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String,
        languageContext: String,
    ): String {
        val normalizer = normalizersByRoot.getOrPut(layout.rootDir.absolutePath) {
            LayoutNormalizer(layout)
        }
        return normalizer.normalize(text, language, languageContext)
    }

    fun shutdown(layout: LitsTtsAssetInstaller.InstalledLayout) {
        normalizersByRoot.remove(layout.rootDir.absolutePath)?.close()
        NativeTnNormalizer.clear(layout.rootDir)
    }

    /**
     * Warm the TN path off the main thread: this pays the one-time startup cost
     * (native lib / child-process spawn + ICU RBNF init + rules-JSON parse +
     * first-time regex-pattern compilation) in the background so it does not land
     * on the critical path of the user's first synthesis. Runs whichever path
     * (JNI in-process or child process) the real requests use, for both en and
     * zh. Idempotent via the per-root cache; best-effort, failures are ignored.
     */
    fun prewarm(layout: LitsTtsAssetInstaller.InstalledLayout) {
        Thread({
            runCatching {
                normalize(layout, "123", "en-US", "en-US")
                normalize(layout, "预热1", "zh-CN", "zh-CN")
                logInfo("TN prewarm complete root=${layout.rootDir.absolutePath}")
            }.onFailure { logWarning("TN prewarm failed", it) }
        }, "lits-tts-tn-prewarm").apply {
            isDaemon = true
            start()
        }
    }

    private class LayoutNormalizer(private val layout: LitsTtsAssetInstaller.InstalledLayout) {
        private val processes = mutableMapOf<String, TnProcess>()
        private val disabledLanguages = mutableSetOf<String>()
        private val frontendRules = FrontendRuleSet.load(layout.frontendRules)

        @Synchronized
        fun normalize(text: String, language: String, languageContext: String): String {
            val cleaned = Normalizer.normalize(text, Normalizer.Form.NFKC)
                .replace(Regex("[\\x00-\\x1f\\x7f-\\x9f]"), "")
                .replace(Regex("\\s+"), " ")
                .trim()
            val isEnglishContext = language == "en-US" || languageContext == "en-US"
            val input = if (isEnglishContext) {
                prepareEnglishInputForTn(cleaned)
            } else {
                prepareInputForTn(cleaned)
            }
            val hasRules = hasTnRules()
            logInfo("TN normalize request language=$language languageContext=$languageContext hasRules=$hasRules input=${input.takeForLog()}")
            if (input.isEmpty()) return text
            if (!hasRules) return input
            return if (isEnglishContext) {
                normalizeSegment(input, "en")
            } else {
                segmentZhEn(input).joinToString("") { (segment, lang) ->
                    preserveSegmentWhitespace(segment, normalizeSegment(segment, lang))
                }
            }
        }

        private fun prepareInputForTn(text: String): String {
            var output = hanziClockMinuteLeadingZeroRegex.replace(text) { match ->
                "${match.groupValues[1]}点零${chineseDigitTextByChar.getValue(match.groupValues[2].single())}分"
            }
            output = frontendRules.apply("pre_tn", output)
            output = protectSemanticNumericReadings(output)
            output = protectTechnicalAsciiReadings(output)
            output = protectVinCodes(output)
            output = protectProductCodes(output)
            output = serialCodeRegex.replace(output) { match ->
                match.groupValues[1] + match.groupValues[2] + normalizeSerialCode(match.groupValues[3])
            }
            return output
        }

        private fun prepareEnglishInputForTn(text: String): String {
            var output = englishAtNumberFifteenRegex.replace(text) { match ->
                match.groupValues[1] + integerTextToEnglishWords(match.groupValues[2]) + match.groupValues[3]
            }
            output = englishLeadingZeroNumberRegex.replace(output) { match ->
                digitSequenceToEnglishWords(match.value)
            }
            output = englishVerificationCodeTailRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToEnglishWords(match.groupValues[2])
            }
            return output
        }

        private fun protectTechnicalAsciiReadings(text: String): String {
            var output = chemicalFormulaRegex.replace(text) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2]) + match.groupValues[3]
            }
            output = technicalAsciiTokenRegex.replace(output) { match ->
                val token = match.groupValues[1]
                if (!token.any { isAsciiLetter(it) } || !token.any { it in technicalSymbolChars }) {
                    token
                } else {
                    normalizeTechnicalAsciiTokenForTn(token)
                }
            }
            return output
        }

        private fun normalizeTechnicalAsciiTokenForTn(token: String): String {
            val output = StringBuilder(token.length)
            var index = 0
            while (index < token.length) {
                val char = token[index]
                when {
                    char.isDigit() -> {
                        val start = index
                        while (index < token.length && token[index].isDigit()) {
                            index += 1
                        }
                        output.append(digitSequenceToHanzi(token.substring(start, index)))
                        if (index < token.length && (token[index] in technicalSymbolChars || isAsciiLetter(token[index]))) {
                            output.append(",")
                        }
                    }
                    isAsciiLetter(char) -> {
                        val start = index
                        while (index < token.length && isAsciiLetter(token[index])) {
                            index += 1
                        }
                        val word = token.substring(start, index)
                        output.append(if (word.equals("lits", ignoreCase = true)) "LITS" else word)
                    }
                    char == '@' -> output.append(" at ")
                    char == '_' -> output.append(" UNDERSCORE ")
                    char == '+' -> output.append("加")
                    char == '-' -> output.append("杠")
                    char == '.' -> output.append("点")
                    char == ':' -> output.append("冒号")
                    char == '/' || char == '\\' -> output.append("斜杠")
                    char == '?' -> output.append("问号")
                    char == '=' -> output.append("等于")
                    char == '&' -> output.append("和")
                    else -> output.append(char)
                }
                if (!char.isDigit() && !isAsciiLetter(char)) {
                    index += 1
                }
            }
            return output.toString().replace(Regex("\\s+"), " ")
        }

        private fun protectSemanticNumericReadings(text: String): String {
            var output = percentNumberRegex.replace(text) { match ->
                "百分之${numberTextToHanzi(match.groupValues[1])}"
            }
            output = percentNumberTextRegex.replace(output) { match ->
                "百分之${numberTextToHanzi(match.groupValues[1])}"
            }
            output = coordinateRegex.replace(output) { match ->
                val prefix = when (match.groupValues[1].uppercase()) {
                    "N" -> "北纬"
                    "E" -> "东经"
                    else -> match.groupValues[1]
                }
                prefix + numberTextToHanzi(match.groupValues[2])
            }
            output = semanticVersionRegex.replace(output) { match ->
                match.groupValues[1] + versionNumberToHanzi(match.groupValues[2])
            }
            output = stockCodeRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2])
            }
            output = roomNumberRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2])
            }
            output = plateCodeRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2]) + ","
            }
            output = idTailRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2]) + match.groupValues[3] + ","
            }
            output = pathSlashNumberRegex.replace(output) { match ->
                match.groupValues[1] + digitSequenceToHanzi(match.groupValues[2]) + ","
            }
            output = kmPerHourRegex.replace(output) { match ->
                numberTextToHanzi(match.groupValues[1]) + "千米每小时"
            }
            output = clockColonMinuteLeadingZeroRegex.replace(output) { match ->
                "${numberTextToHanzi(match.groupValues[1])}点零${chineseDigitTextByChar.getValue(match.groupValues[2].single())}"
            }
            output = yearBeforeNianRegex.replace(output) { match ->
                digitSequenceToHanzi(match.groupValues[1]) + "年"
            }
            return output
        }

        private fun protectVinCodes(text: String): String =
            vinCodeRegex.replace(text) { match ->
                match.groupValues[1] + normalizeSerialCode(match.groupValues[2])
            }

        private fun protectProductCodes(text: String): String =
            productCodeRegex.replace(text) { match ->
                match.groupValues[1] + normalizeSerialCode(match.groupValues[2]) + match.groupValues[3]
            }

        private fun normalizeSerialCode(code: String): String = buildString {
            code.forEach { char ->
                append(chineseDigitTextByChar[char] ?: char)
            }
        }

        private fun numberTextToHanzi(text: String): String {
            val parts = text.split('.', limit = 2)
            val integer = integerTextToHanzi(parts[0])
            if (parts.size == 1) return integer
            return integer + "点" + parts[1].map { chineseDigitTextByChar.getValue(it) }.joinToString("")
        }

        private fun integerTextToHanzi(text: String): String {
            val value = text.toIntOrNull() ?: return digitSequenceToHanzi(text)
            if (value == 0) return "零"
            if (value < 10) return chineseDigitTextByChar.getValue(value.digitToChar())
            if (value < 20) {
                val ones = value % 10
                return "十" + if (ones == 0) "" else chineseDigitTextByChar.getValue(ones.digitToChar())
            }
            if (value < 100) {
                val tens = value / 10
                val ones = value % 10
                return chineseDigitTextByChar.getValue(tens.digitToChar()) + "十" +
                    if (ones == 0) "" else chineseDigitTextByChar.getValue(ones.digitToChar())
            }
            val hundreds = value / 100
            val remainder = value % 100
            return chineseDigitTextByChar.getValue(hundreds.digitToChar()) + "百" +
                when {
                    remainder == 0 -> ""
                    remainder < 10 -> "零" + chineseDigitTextByChar.getValue(remainder.digitToChar())
                    else -> integerTextToHanzi(remainder.toString())
                }
        }

        private fun digitSequenceToHanzi(text: String): String =
            text.map { chineseDigitTextByChar.getValue(it) }.joinToString("")

        private fun digitSequenceToEnglishWords(text: String): String =
            text.map { englishDigitWordByChar.getValue(it) }.joinToString(" ")

        private fun integerTextToEnglishWords(text: String): String {
            val value = text.toIntOrNull() ?: return digitSequenceToEnglishWords(text)
            if (value < 10) return englishDigitWordByChar.getValue(value.digitToChar())
            englishTeenWordByValue[value]?.let { return it }
            if (value < 100) {
                val tens = (value / 10) * 10
                val ones = value % 10
                return if (ones == 0) {
                    englishTensWordByValue.getValue(tens)
                } else {
                    englishTensWordByValue.getValue(tens) + " " + englishDigitWordByChar.getValue(ones.digitToChar())
                }
            }
            return digitSequenceToEnglishWords(text)
        }

        private fun versionNumberToHanzi(text: String): String =
            text.split('.').joinToString("点", transform = ::digitSequenceToHanzi)

        private fun hasTnRules(): Boolean =
            layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_V2_ZH).isFile &&
                layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_V2_EN).isFile &&
                layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_ZH_PINYIN).isFile

        private fun normalizeSegment(text: String, lang: String): String {
            if (text.isBlank()) return text
            if (lang in disabledLanguages) return text
            try {
                NativeTnNormalizer.normalize(layout.rootDir, lang, text)?.let { normalized ->
                    logInfo("TN native path used lang=$lang input=${text.takeForLog()} output=${normalized.takeForLog()}")
                    return normalized
                }
            } catch (error: Throwable) {
                logWarning("native TN normalize failed; falling back to process lang=$lang", error)
            }
            val binary = when (lang) {
                "en" -> layout.tnEnTts
                else -> layout.tnZhTts
            }
            return try {
                val process = processes.getOrPut(lang) {
                    TnProcess.start(binary, layout.rootDir)
                }
                process.normalize(text).also { normalized ->
                    logInfo("TN process path used lang=$lang binary=${binary.absolutePath} input=${text.takeForLog()} output=${normalized.takeForLog()}")
                }
            } catch (error: Throwable) {
                logWarning("TN normalize failed; restarting lang=$lang binary=${binary.absolutePath}", error)
                processes.remove(lang)?.close()
                try {
                    val restarted = TnProcess.start(binary, layout.rootDir)
                    processes[lang] = restarted
                    restarted.normalize(text).also { normalized ->
                        logInfo("TN process retry path used lang=$lang binary=${binary.absolutePath} input=${text.takeForLog()} output=${normalized.takeForLog()}")
                    }
                } catch (retryError: Throwable) {
                    logError("TN normalize retry failed; disabling TN for lang=$lang", retryError)
                    processes.remove(lang)?.close()
                    disabledLanguages += lang
                    text
                }
            }
        }

        @Synchronized
        fun close() {
            processes.values.forEach { process ->
                runCatching { process.close() }
            }
            processes.clear()
            disabledLanguages.clear()
        }

        private fun segmentZhEn(text: String): List<Pair<String, String>> {
            val segments = mutableListOf<Pair<String, String>>()
            var index = 0
            while (index < text.length) {
                val char = text[index]
                if (isAsciiLetter(char)) {
                    val end = scanAsciiRun(text, index)
                    val segment = text.substring(index, end)
                    val lang = protectedAsciiRunLang(text, index, end) ?: "en"
                    segments += segment to lang
                    index = end
                } else {
                    val end = scanNonAsciiRun(text, index)
                    segments += text.substring(index, end) to "zh"
                    index = end
                }
            }
            return segments
        }

        private fun scanAsciiRun(text: String, start: Int): Int {
            var index = start
            while (index < text.length) {
                val char = text[index]
                val allowedPunctuation = char in charArrayOf('\'', '.', '_', '-')
                if (!isAsciiLetter(char) && !char.isDigit() && !allowedPunctuation) break
                index += 1
            }
            return index
        }

        private fun scanNonAsciiRun(text: String, start: Int): Int {
            var index = start
            while (index < text.length && (!isAsciiLetter(text[index]) || isAsciiCelsiusUnit(text, index))) {
                index += 1
            }
            return index
        }

        private fun isAsciiCelsiusUnit(text: String, index: Int): Boolean =
            index > 0 && text[index - 1] == '°' && (text[index] == 'C' || text[index] == 'c')

        private fun protectedAsciiRunLang(text: String, start: Int, end: Int): String? {
            val run = text.substring(start, end)
            if (isProtectedChemicalFormula(run)) return "en"
            if (isChineseContextCode(text, start, end, run)) return "zh"
            return null
        }

        private fun isProtectedChemicalFormula(run: String): Boolean =
            run == "SO2" || run == "CO2" || run == "C6H12O6"

        private fun isChineseContextCode(text: String, start: Int, end: Int, run: String): Boolean {
            val touchesChinese = (start > 0 && isCjk(text[start - 1])) || (end < text.length && isCjk(text[end]))
            if (!touchesChinese) return false
            val hasDigit = run.any { it.isDigit() }
            val upperCount = run.count { it in 'A'..'Z' }
            val hasLower = run.any { it in 'a'..'z' }
            val followsPlateProvince = start > 0 && text[start - 1] in PLATE_PROVINCES
            val isPercentileCode = run.matches(PERCENTILE_CODE)
            return hasDigit && !hasLower && (upperCount >= 1 || followsPlateProvince || isPercentileCode)
        }

        private fun isCjk(char: Char): Boolean =
            char in '\u4e00'..'\u9fff'

        private fun isAsciiLetter(char: Char): Boolean =
            char in 'a'..'z' || char in 'A'..'Z'

        companion object {
            private const val PLATE_PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"
            private val PERCENTILE_CODE = Regex("P\\d{1,3}")
            private val hanziClockMinuteLeadingZeroRegex = Regex("([零一二三四五六七八九十两]+)点0([1-9])分")
            private val percentNumberRegex = Regex("(\\d+(?:\\.\\d+)?)\\s?[%％]")
            private val percentNumberTextRegex = Regex("(\\d+(?:\\.\\d+)?)\\s?百分号")
            private val clockColonMinuteLeadingZeroRegex = Regex("(?<!\\d)(\\d{1,2}):0([0-9])(?!\\d)")
            private val yearBeforeNianRegex = Regex("(?<!\\d)(\\d{4})\\s*年")
            private val semanticVersionRegex = Regex("(?<![A-Za-z0-9])([vV])(\\d+(?:\\.\\d+)+)(?![A-Za-z0-9])")
            private val technicalAsciiTokenRegex = Regex("(?<![A-Za-z0-9])([A-Za-z0-9./\\\\_@:?=&#%+\\-]*[A-Za-z0-9])(?![A-Za-z0-9])")
            private val technicalSymbolChars = setOf('.', '/', '\\', '_', '@', ':', '?', '=', '&', '#', '%', '+', '-')
            private val chemicalFormulaRegex = Regex("\\b(H|CO)(\\d+)(O?)\\b")
            private val roomNumberRegex = Regex("((?:房间|房号)(?:是|为)?\\s*)(\\d{3,4})(?!\\d)")
            private val stockCodeRegex = Regex("(股票\\s*)(\\d{6})(?!\\d)")
            private val plateCodeRegex = Regex("((?:车牌号?|号牌)\\s*[\\u4e00-\\u9fff]?\\s*[A-Za-z])(\\d{3,6})(?!\\d)")
            private val idTailRegex = Regex("((?:身份证尾号|尾号)\\s*)(\\d+)([A-Za-z])(?![A-Za-z0-9])")
            private val pathSlashNumberRegex = Regex("(/)(\\d+)(?=/)")
            private val kmPerHourRegex = Regex("(\\d+)\\s*km/h", RegexOption.IGNORE_CASE)
            private val coordinateRegex = Regex("(?<![A-Za-z])([NE])\\s*(\\d+(?:\\.\\d+)?)", RegexOption.IGNORE_CASE)
            private val vinCodeRegex = Regex("((?:车架号\\s*)?(?:VIN\\s+))([A-HJ-NPR-Z0-9]{8,17})(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
            private val productCodeRegex = Regex("(?<![A-Za-z0-9])(vocos|Office)(\\d+)(k?)(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
            private val serialCodeRegex = Regex("((?:设备)?(?:序列号|编号)|S/N|SN)(\\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\\d[A-Z0-9]*)")
            private val englishAtNumberFifteenRegex = Regex("\\b(at\\s+)(\\d{2})(\\s+fifteen\\b)", RegexOption.IGNORE_CASE)
            private val englishLeadingZeroNumberRegex = Regex("\\b0\\d+\\b")
            private val englishVerificationCodeTailRegex = Regex(
                "\\b((?:verification\\s+)?code\\s+is\\s+(?:(?:[A-Z]|zero|one|two|three|four|five|six|seven|eight|nine)\\s+){2,})(\\d{1,4})(?=\\b)",
                RegexOption.IGNORE_CASE,
            )
            private val chineseDigitTextByChar = mapOf(
                '0' to "零",
                '1' to "一",
                '2' to "二",
                '3' to "三",
                '4' to "四",
                '5' to "五",
                '6' to "六",
                '7' to "七",
                '8' to "八",
                '9' to "九",
            )
            private val englishDigitWordByChar = mapOf(
                '0' to "zero",
                '1' to "one",
                '2' to "two",
                '3' to "three",
                '4' to "four",
                '5' to "five",
                '6' to "six",
                '7' to "seven",
                '8' to "eight",
                '9' to "nine",
            )
            private val englishTeenWordByValue = mapOf(
                10 to "ten",
                11 to "eleven",
                12 to "twelve",
                13 to "thirteen",
                14 to "fourteen",
                15 to "fifteen",
                16 to "sixteen",
                17 to "seventeen",
                18 to "eighteen",
                19 to "nineteen",
            )
            private val englishTensWordByValue = mapOf(
                20 to "twenty",
                30 to "thirty",
                40 to "forty",
                50 to "fifty",
                60 to "sixty",
                70 to "seventy",
                80 to "eighty",
                90 to "ninety",
            )
        }
    }

    private class TnProcess private constructor(
        private val process: Process,
        private val writer: BufferedWriter,
        private val reader: BufferedReader,
    ) {
        @Synchronized
        fun normalize(text: String): String {
            if (!process.isAlive) {
                throw IllegalStateException("TN process exited before normalize")
            }
            writer.write(text)
            writer.newLine()
            writer.flush()
            val normalized = reader.readLine()
                ?: throw IllegalStateException("TN process exited without output")
            return normalized.trim().takeUnless { it.isEmpty() } ?: text
        }

        @Synchronized
        fun close() {
            runCatching { writer.close() }
            runCatching { reader.close() }
            if (process.isAlive) {
                process.destroy()
                runCatching {
                    if (!process.waitFor(200, TimeUnit.MILLISECONDS)) {
                        process.destroyForcibly()
                    }
                }
            }
        }

        companion object {
            fun start(binary: File, workingDir: File): TnProcess {
                binary.setExecutable(true, true)
                logInfo("TN process start binary=${binary.absolutePath} exists=${binary.isFile} canExecute=${binary.canExecute()} workingDir=${workingDir.absolutePath}")
                val process = ProcessBuilder(binary.absolutePath)
                    .directory(workingDir)
                    .apply {
                        environment()["TTS_RULES_ROOT"] = workingDir.absolutePath
                        environment()["TTS_RULES_FORMAT"] = "v2"
                    }
                    .start()
                Thread({
                    process.errorStream.bufferedReader().use { error ->
                        while (error.readLine() != null) {
                            // Drain stderr so the TN process cannot block on a full error pipe.
                        }
                    }
                }, "lits-tts-tn-stderr-${binary.name}").apply {
                    isDaemon = true
                    start()
                }
                return TnProcess(
                    process = process,
                    writer = BufferedWriter(OutputStreamWriter(process.outputStream, Charsets.UTF_8)),
                    reader = BufferedReader(InputStreamReader(process.inputStream, Charsets.UTF_8)),
                )
            }
        }
    }

    internal fun preserveSegmentWhitespace(segment: String, normalized: String): String {
        var output = normalized
        if (segment.firstOrNull()?.isWhitespace() == true && output.firstOrNull()?.isWhitespace() != true) {
            output = " $output"
        }
        if (segment.lastOrNull()?.isWhitespace() == true && output.lastOrNull()?.isWhitespace() != true) {
            output += " "
        }
        return output
    }

    private fun logWarning(message: String, error: Throwable) {
        try {
            Log.w(TAG, message, error)
        } catch (_: Throwable) {
            // Android Log is not mocked in local JVM tests; TN should still be testable there.
        }
    }

    private fun logInfo(message: String) {
        try {
            Log.i(TAG, message)
        } catch (_: Throwable) {
            // Android Log is not mocked in local JVM tests; TN should still be testable there.
        }
    }

    private fun logError(message: String, error: Throwable) {
        try {
            Log.e(TAG, message, error)
        } catch (_: Throwable) {
            // Android Log is not mocked in local JVM tests; TN should still be testable there.
        }
    }

    private fun String.takeForLog(maxLength: Int = 160): String =
        if (length <= maxLength) this else take(maxLength) + "...(len=$length)"

    private const val TAG = "LitsTn"
}
