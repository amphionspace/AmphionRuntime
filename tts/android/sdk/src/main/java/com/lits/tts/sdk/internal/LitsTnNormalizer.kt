package com.lits.tts.sdk.internal

import android.util.Log
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap

internal object LitsTnNormalizer {
    private val normalizersByRoot = ConcurrentHashMap<String, LayoutNormalizer>()
    private val lastProfileByThread = ThreadLocal<TnNormalizeProfile?>()

    /**
     * Opt-in TN prewarm. DEFAULT OFF so it never affects a strict cold-start
     * benchmark: with this false, prewarm() is a no-op and startup follows the
     * pure lazy cold path. Enable it ONLY when the target metric is end-to-end
     * first-synthesis latency and background pre-initialization is allowed — then
     * the TN warm-up overlaps the (heavier) ONNX model load. Note: when enabled,
     * warm-up shares the per-layout normalize lock, so a first request in the
     * other language may briefly wait behind the warm-up.
     */
    @Volatile
    var prewarmEnabled: Boolean = false

    @Volatile
    var batchNativeEnabled: Boolean = false

    /**
     * Opt-in TN fast path. When enabled, text that contains ONLY hanzi and a
     * small set of common Chinese sentence punctuation skips the native TN call
     * entirely (native TN rules target digits/ASCII/symbols, so the call would
     * be an identity transform for such input). Any digit, letter, symbol, or
     * uncommon character routes back to the full native path.
     */
    @Volatile
    var fastPathEnabled: Boolean = false

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
        if (!prewarmEnabled) return
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

    fun lastProfileSummary(): String? =
        lastProfileByThread.get()?.toSummary()

    private class LayoutNormalizer(private val layout: LitsTtsAssetInstaller.InstalledLayout) {
        private val disabledLanguages = mutableSetOf<String>()
        private val frontendRules = FrontendRuleSet.load(layout.frontendRules)

        @Synchronized
        fun normalize(text: String, language: String, languageContext: String): String {
            val totalStartedAt = System.nanoTime()
            val cleanStartedAt = System.nanoTime()
            val cleaned = Normalizer.normalize(text, Normalizer.Form.NFKC)
                .replace(Regex("[\\x00-\\x1f\\x7f-\\x9f]"), "")
                .replace(Regex("\\s+"), " ")
                .trim()
            val cleanMs = elapsedMs(cleanStartedAt)
            val isEnglishContext = language == "en-US" || languageContext == "en-US"
            val prepareStartedAt = System.nanoTime()
            val input = if (isEnglishContext) {
                prepareEnglishInputForTn(cleaned)
            } else {
                prepareInputForTn(cleaned)
            }
            val prepareMs = elapsedMs(prepareStartedAt)
            val hasRulesStartedAt = System.nanoTime()
            val hasRules = hasTnRules()
            val hasRulesMs = elapsedMs(hasRulesStartedAt)
            logInfo("TN normalize request language=$language languageContext=$languageContext hasRules=$hasRules input=${input.takeForLog()}")
            if (input.isEmpty()) {
                lastProfileByThread.set(
                    TnNormalizeProfile(
                        totalMs = elapsedMs(totalStartedAt),
                        cleanMs = cleanMs,
                        prepareMs = prepareMs,
                        hasRulesMs = hasRulesMs,
                        segmentMs = 0L,
                        nativeMs = 0L,
                        joinMs = 0L,
                        preserveWhitespaceMs = 0L,
                        appendMs = 0L,
                        segmentCount = 0,
                        nativeCalls = emptyList(),
                    ),
                )
                return text
            }
            if (!hasRules) {
                lastProfileByThread.set(
                    TnNormalizeProfile(
                        totalMs = elapsedMs(totalStartedAt),
                        cleanMs = cleanMs,
                        prepareMs = prepareMs,
                        hasRulesMs = hasRulesMs,
                        segmentMs = 0L,
                        nativeMs = 0L,
                        joinMs = 0L,
                        preserveWhitespaceMs = 0L,
                        appendMs = 0L,
                        segmentCount = 0,
                        nativeCalls = emptyList(),
                    ),
                )
                return input
            }
            if (fastPathEnabled && input.all(::isTnFastPathSafe)) {
                lastProfileByThread.set(
                    TnNormalizeProfile(
                        totalMs = elapsedMs(totalStartedAt),
                        cleanMs = cleanMs,
                        prepareMs = prepareMs,
                        hasRulesMs = hasRulesMs,
                        segmentMs = 0L,
                        nativeMs = 0L,
                        joinMs = 0L,
                        preserveWhitespaceMs = 0L,
                        appendMs = 0L,
                        segmentCount = 0,
                        nativeCalls = emptyList(),
                        fastPath = true,
                    ),
                )
                return input
            }
            val nativeCalls = mutableListOf<TnNativeCallProfile>()
            val segmentStartedAt = System.nanoTime()
            // Match the Python one-shot TN path: choose one locale for the
            // complete utterance, then send the complete utterance through TN.
            // For zh-en, Chinese script selects zh_tts; otherwise en_tts.
            val tnLang = if (isEnglishContext || input.none(::isHanziForTn)) "en" else "zh"
            val segments = listOf(input to tnLang)
            val segmentMs = elapsedMs(segmentStartedAt)
            val joinStartedAt = System.nanoTime()
            // Keep the existing optional JNI batch path for benchmark
            // compatibility, but it now contains exactly one utterance.
            val batchOutputsByIndex = if (batchNativeEnabled) {
                runCatching {
                    NativeTnNormalizer.normalizeBatch(
                        layout.rootDir,
                        arrayOf(tnLang),
                        arrayOf(input),
                    )
                }.onFailure {
                    logWarning("native TN batch normalize failed; falling back to scalar call", it)
                }.getOrNull()
                    ?.takeIf { it.size == 1 }
                    ?.let { outputs -> mapOf(0 to outputs[0]) }
                    ?: emptyMap()
            } else {
                emptyMap()
            }
            val batchProfile = if (batchOutputsByIndex.isNotEmpty()) {
                NativeTnNormalizer.lastBatchCallProfile()
            } else {
                null
            }
            val output = batchOutputsByIndex[0] ?: normalizeSegment(input, tnLang, nativeCalls)
            val joinMs = elapsedMs(joinStartedAt)
            lastProfileByThread.set(
                TnNormalizeProfile(
                    totalMs = elapsedMs(totalStartedAt),
                    cleanMs = cleanMs,
                    prepareMs = prepareMs,
                    hasRulesMs = hasRulesMs,
                    segmentMs = segmentMs,
                    nativeMs = batchProfile?.wallMs ?: nativeCalls.sumOf { it.elapsedMs },
                    joinMs = joinMs,
                    preserveWhitespaceMs = 0L,
                    appendMs = 0L,
                    segmentCount = segments.size,
                    nativeCalls = nativeCalls,
                    batchProfile = batchProfile,
                ),
            )
            return output
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

        private fun isHanziForTn(char: Char): Boolean =
            char in '\u4e00'..'\u9fff'

        private fun isTnFastPathSafe(char: Char): Boolean =
            isHanziForTn(char) || char in " ，。！？；：、（）《》「」『』“”‘’—…,.!?;:()[]<>\"'"

        private fun normalizeSegment(
            text: String,
            lang: String,
            nativeCalls: MutableList<TnNativeCallProfile>,
        ): String {
            if (text.isBlank()) return text
            if (lang in disabledLanguages) return text
            try {
                val startedAt = System.nanoTime()
                NativeTnNormalizer.normalize(layout.rootDir, lang, text)?.let { normalized ->
                    val nativeProfile = NativeTnNormalizer.lastCallProfile()
                    nativeCalls += TnNativeCallProfile(
                        lang = lang,
                        inputLength = text.length,
                        outputLength = normalized.length,
                        elapsedMs = elapsedMs(startedAt),
                        availabilityMs = nativeProfile?.availabilityMs ?: 0L,
                        jniMs = nativeProfile?.jniMs ?: 0L,
                    )
                    logInfo("TN native path used lang=$lang input=${text.takeForLog()} output=${normalized.takeForLog()}")
                    return normalized
                }
            } catch (error: Throwable) {
                logWarning("native TN normalize failed; disabling TN for lang=$lang", error)
            }
            disabledLanguages += lang
            return text
        }

        @Synchronized
        fun close() {
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

    private data class TnNormalizeProfile(
        val totalMs: Long,
        val cleanMs: Long,
        val prepareMs: Long,
        val hasRulesMs: Long,
        val segmentMs: Long,
        val nativeMs: Long,
        val joinMs: Long,
        val preserveWhitespaceMs: Long,
        val appendMs: Long,
            val segmentCount: Int,
            val nativeCalls: List<TnNativeCallProfile>,
            val batchProfile: NativeTnNormalizer.BatchCallProfile? = null,
            val fastPath: Boolean = false,
        ) {
        fun toSummary(): String = buildString {
            append("total=").append(totalMs).append("ms")
            append(",clean=").append(cleanMs).append("ms")
            append(",prepare=").append(prepareMs).append("ms")
            append(",hasRules=").append(hasRulesMs).append("ms")
            append(",segment=").append(segmentMs).append("ms")
            append(",native=").append(nativeMs).append("ms")
            append(",nativeJni=").append(batchProfile?.jniMs ?: nativeCalls.sumOf { it.jniMs }).append("ms")
            append(",nativeAvailability=").append(
                batchProfile?.availabilityMs ?: nativeCalls.sumOf { it.availabilityMs },
            ).append("ms")
            append(",nativeBatch=").append(batchProfile != null)
            append(",fastPath=").append(fastPath)
            batchProfile?.let {
                append(",batchItems=").append(it.itemCount)
            }
            append(",joinWall=").append(joinMs).append("ms")
            append(",preserveWhitespace=").append(preserveWhitespaceMs).append("ms")
            append(",append=").append(appendMs).append("ms")
            append(",joinOverhead=").append(
                (joinMs - nativeMs - preserveWhitespaceMs - appendMs).coerceAtLeast(0L),
            ).append("ms")
            append(",segments=").append(segmentCount)
            if (nativeCalls.isNotEmpty()) {
                append(",nativeCalls=")
                append(
                    nativeCalls.joinToString("|") { call ->
                        "${call.lang}:wall=${call.elapsedMs}ms,jni=${call.jniMs}ms,available=${call.availabilityMs}ms,${call.inputLength}->${call.outputLength}"
                    },
                )
            }
        }
    }

    private data class TnNativeCallProfile(
        val lang: String,
        val inputLength: Int,
        val outputLength: Int,
        val elapsedMs: Long,
        val availabilityMs: Long,
        val jniMs: Long,
    )

    private fun elapsedMs(startedAt: Long): Long = (System.nanoTime() - startedAt) / 1_000_000L

    private const val TAG = "LitsTn"
}
