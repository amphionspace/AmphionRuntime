package com.lits.tts.sdk.internal

import android.util.Log
import com.lits.tts.sdk.TtsErrorCode
import java.io.File
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsFrontend {
    private const val METRIC_TAG = "LitsFrontendMetric"
    private const val DETAIL_TAG = "LitsFrontendDetail"
    private const val LOG_CHUNK_SIZE = 3200
    private val traceSequence = AtomicLong(0L)
    private val resourcesByRoot = ConcurrentHashMap<String, FrontendResources>()
    private val pinyinSyllableRegex = Regex("^[a-z]+[0-6]$")
    private val hanziRegex = Regex("[\\u4e00-\\u9fff]")
    private val punctuation = setOf(',', '.', '!', '?', ';', ':', '\'', '"', '(', ')', '[', ']', '<', '>', '-')
    private val sentenceEndPunctuation = setOf('.', '!', '?', ';', ',', '\u2026')
    private val attachedSentenceSuffix = setOf('"', '\'', ')', ']', '}', '>', '\u201D', '\u2019', '\u300B', '\u3011')
    private val ENGLISH_ABBREVIATIONS = setOf(
        "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "mt", "vs", "etc", "fig", "no",
        "e.g", "i.e", "a.m", "p.m", "u.s", "u.k",
    )
    private val ACRONYM_AT_END_REGEX = Regex("(?:^|\\s)(?:[A-Za-z]\\.){2,}$")
    private const val MIN_WEAK_PUNCTUATION_SEGMENT_CHARS = 24
    private const val MIN_SHORT_SYMBOL_SEGMENT_CHARS = 8
    private val fullwidthPunctuation = mapOf(
        '\uFF0C' to ",",
        '\u3002' to ".",
        '\uFF01' to "!",
        '\uFF1F' to "?",
        '\uFF1B' to ";",
        '\uFF1A' to ":",
        '\u3001' to ",",
        '\u2018' to "'",
        '\u2019' to "'",
        '\u201C' to "\"",
        '\u201D' to "\"",
        '\u3010' to "[",
        '\u3011' to "]",
        '\uFF08' to "(",
        '\uFF09' to ")",
        '\u300A' to "<",
        '\u300B' to ">",
        '\u2014' to "-",
        '\u2013' to "-",
        '\u22EF' to "\u2026",
        '\u00B7' to ".",
    )
    private val zhEnFrontendCharReplacements = mapOf(
        '/' to "斜杠",
        '\\' to "反斜杠",
        '^' to "幂",
        '\u2070' to "零",
        '\u00B9' to "一",
        '\u00B2' to "二",
        '\u00B3' to "三",
        '\u2074' to "四",
        '\u2075' to "五",
        '\u2076' to "六",
        '\u2077' to "七",
        '\u2078' to "八",
        '\u2079' to "九",
        '\u2080' to "零",
        '\u2081' to "一",
        '\u2082' to "二",
        '\u2083' to "三",
        '\u2084' to "四",
        '\u2085' to "五",
        '\u2086' to "六",
        '\u2087' to "七",
        '\u2088' to "八",
        '\u2089' to "九",
    )
    private val zhEnAsciiSymbolText = mapOf(
        '@' to "艾特",
        '#' to "井号",
        '$' to "美元",
        '%' to "百分号",
        '\uFF05' to "百分号",
        '&' to "和",
        '*' to "星号",
        '+' to "加",
        '=' to "等于",
        '_' to "下划线",
        '|' to "竖线",
        '~' to "波浪线",
    )
    private val symbolToSafePunctuation = mapOf(
        '{' to "(",
        '}' to ")",
        '\uFF5B' to "(",
        '\uFF5D' to ")",
        '\u300C' to "\"",
        '\u300D' to "\"",
        '\u300E' to "\"",
        '\u300F' to "\"",
        '\u3014' to "[",
        '\u3015' to "]",
        '\u3016' to "[",
        '\u3017' to "]",
        '\u3018' to "[",
        '\u3019' to "]",
        '\u301A' to "[",
        '\u301B' to "]",
        '\uFF3B' to "[",
        '\uFF3D' to "]",
        '\uFF1C' to "<",
        '\uFF1E' to ">",
        '\uFF0F' to ",",
        '\uFF3C' to ",",
        '\uFF20' to ",",
        '\uFF03' to ",",
        '\uFF04' to ",",
        '\uFF05' to ",",
        '\uFF06' to ",",
        '\uFF0A' to ",",
        '\uFF0B' to ",",
        '\uFF1D' to ",",
        '\uFF3F' to ",",
        '\uFF5C' to ",",
        '\uFF5E' to ",",
        '\u2190' to ",",
        '\u2191' to ",",
        '\u2192' to ",",
        '\u2193' to ",",
        '\u21D2' to ",",
        '\u2605' to ",",
        '\u2606' to ",",
        '\u2713' to ",",
        '\u2714' to ",",
        '\u2715' to ",",
        '\u2716' to ",",
    )
    private val percentNumberRegex = Regex("(\\d+(?:\\.\\d+)?)[%％]")
    private val commaIntegerCurrencyRegex = Regex("(?<!\\d)(\\d{1,3}(?:,\\d{3})+)\\.00(?=元)")
    private val thousandsSeparatorRegex = Regex("(?<=\\d),(?=\\d{3}(?:\\D|$))")
    private val clockMinuteLeadingZeroRegex = Regex("(?<!\\d)(\\d{1,2})点0([1-9])分")
    private val hanziClockMinuteLeadingZeroRegex = Regex("([零一二三四五六七八九十两]+)点0([1-9])分")
    private val durationMinuteLeadingZeroRegex = Regex("(?<!\\d)(\\d+)小时0([1-9])分钟")
    private val yearMonthLeadingZeroRegex = Regex("(\\d{2,4}年)0([1-9])月")
    private val yearMonthRegex = Regex("(\\d{2,4}年)(\\d{1,2})月")
    private val monthDayLeadingZeroRegex = Regex("(月)0([1-9])日")
    private val monthDayRegex = Regex("(月)(\\d{1,2})(日|号)")
    private val negativeTemperatureRegex = Regex("((?:气温|温度|体温))-(\\d+(?:\\.\\d+)?)(度|℃)")
    private val negativeTemperatureRangeRegex = Regex("(温度范围是)-(\\d+(?:\\.\\d+)?)到(\\d+(?:\\.\\d+)?)(度|℃)")
    private val versionNumberWithSuffixRegex = Regex("(?<!\\d)(\\d+(?:\\.\\d+){2,})(?=[-A-Za-z])")
    private val digitDotRegex = Regex("(?<=\\d)\\.(?=\\d)")
    private val hanziDigitDotRegex = Regex("(?<=[零一二三四五六七八九十百千万两])\\.(?=[零一二三四五六七八九十百千万两])")
    private val leadingDotAsciiTokenRegex = Regex("(?<![A-Za-z0-9])\\.(?=[A-Za-z0-9])")
    private val urlSchemeSeparatorRegex = Regex("(?<![A-Za-z0-9])(https?|ftp)://", RegexOption.IGNORE_CASE)
    private val caretPowerTwoRegex = Regex("\\^(?:2|二)")
    private val technicalAsciiTokenRegex = Regex("(?<![A-Za-z0-9])([A-Za-z0-9./\\\\_@:?=&#%+\\-]*[A-Za-z0-9])(?![A-Za-z0-9])")
    private val serialCodeRegex = Regex("((?:设备)?(?:序列号|编号)|S/N|SN)(\\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\\d[A-Z0-9]*)")
    private val vinCodeRegex = Regex("((?:车架号\\s*)?(?:VIN\\s+))([A-HJ-NPR-Z0-9]{8,17})(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
    private val productCodeRegex = Regex("(?<![A-Za-z0-9])(vocos|Office)(\\d+)(k?)(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
    private val arpabetBoundaryTokens = setOf("/", "|", "_")
    private const val CHINESE_DIGIT_SEQUENCE_CHARS = "零〇一二三四五六七八九两幺"
    private val technicalSymbolReadings = mapOf(
        '.' to "点",
        ':' to "冒号",
        '/' to "斜杠",
        '\\' to "反斜杠",
        '?' to "问号",
        '=' to "等于",
        '&' to "和",
        '@' to "艾特",
        '_' to "下划线",
        '#' to "井号",
        '+' to "加",
        '-' to "杠",
    )
    private val englishDigitWordByChar = mapOf(
        '0' to "ZERO",
        '1' to "ONE",
        '2' to "TWO",
        '3' to "THREE",
        '4' to "FOUR",
        '5' to "FIVE",
        '6' to "SIX",
        '7' to "SEVEN",
        '8' to "EIGHT",
        '9' to "NINE",
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
    private val letterPhonesByChar = mapOf(
        'A' to listOf("EY1"),
        'B' to listOf("B", "IY1"),
        'C' to listOf("S", "IY1"),
        'D' to listOf("D", "IY1"),
        'E' to listOf("IY1"),
        'F' to listOf("EH1", "F"),
        'G' to listOf("JH", "IY1"),
        'H' to listOf("EY1", "CH"),
        'I' to listOf("AY1"),
        'J' to listOf("JH", "EY1"),
        'K' to listOf("K", "EY1"),
        'L' to listOf("EH1", "L"),
        'M' to listOf("EH1", "M"),
        'N' to listOf("EH1", "N"),
        'O' to listOf("OW1"),
        'P' to listOf("P", "IY1"),
        'Q' to listOf("K", "Y", "UW1"),
        'R' to listOf("AA1", "R"),
        'S' to listOf("EH1", "S"),
        'T' to listOf("T", "IY1"),
        'U' to listOf("Y", "UW1"),
        'V' to listOf("V", "IY1"),
        'W' to listOf("D", "AH1", "B", "AH0", "L", "Y", "UW0"),
        'X' to listOf("EH1", "K", "S"),
        'Y' to listOf("W", "AY1"),
        'Z' to listOf("Z", "IY1"),
    )
    private val acronymWordReadings = setOf("SIM")
    private val englishMergeRules = listOf(
        listOf("t", "\u0279") to "t\u0279",
        listOf("d", "\u0279") to "d\u0279",
        listOf("t", "s") to "ts",
        listOf("d", "z") to "dz",
        listOf("\u026A", "\u0279") to "\u026A\u0279",
        listOf("o\u02D0", "\u0279") to "o\u02D0\u0279",
    )

    fun encode(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String,
        languageContext: String,
    ): LongArray {
        val traceId = nextTraceId()
        val normalizedText = LitsTnNormalizer.normalize(layout, text, language, languageContext)
        return encodeNormalizedInternal(
            layout = layout,
            rawText = text,
            normalizedText = normalizedText,
            language = language,
            languageContext = languageContext,
            alreadyNormalized = false,
            traceId = traceId,
        )
    }

    fun encodeNormalized(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        normalizedText: String,
        language: String,
        languageContext: String,
    ): LongArray {
        return encodeNormalizedInternal(
            layout = layout,
            rawText = normalizedText,
            normalizedText = normalizedText,
            language = language,
            languageContext = languageContext,
            alreadyNormalized = true,
            traceId = nextTraceId(),
        )
    }

    private fun encodeNormalizedInternal(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        rawText: String,
        normalizedText: String,
        language: String,
        languageContext: String,
        alreadyNormalized: Boolean,
        traceId: Long,
    ): LongArray {
        val resources = resources(layout)
        val tokenization = tokenizeDetailed(resources, normalizedText, language, languageContext, traceId)
        val ids = tokenization.tokens.map { token ->
            resources.symbolToId[token] ?: throw unsupported("frontend token is not in zh_en_symbols.json: $token")
        }
        val tokenIds = ids.map { it.toLong() }.toLongArray()
        logFrontendMetric(
            traceId = traceId,
            rawText = rawText,
            tnText = normalizedText,
            language = language,
            languageContext = languageContext,
            alreadyNormalized = alreadyNormalized,
            tokenization = tokenization,
            tokenIds = tokenIds,
        )
        return tokenIds
    }

    internal fun debugTokensForTest(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String,
        languageContext: String,
    ): List<String> {
        val resources = resources(layout)
        val normalizedText = LitsTnNormalizer.normalize(layout, text, language, languageContext)
        return tokenize(resources, normalizedText, language, languageContext)
    }

    internal fun debugTokensForNormalizedForTest(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        normalizedText: String,
        language: String,
        languageContext: String,
    ): List<String> {
        val resources = resources(layout)
        return tokenize(resources, normalizedText, language, languageContext)
    }

    fun preload(layout: LitsTtsAssetInstaller.InstalledLayout) {
        resources(layout)
    }

    private data class TokenizationResult(
        val inputText: String,
        val preprocessedText: String,
        val normalizedText: String,
        val tokens: List<String>,
    )

    private fun nextTraceId(): Long = traceSequence.incrementAndGet()

    private fun logFrontendMetric(
        traceId: Long,
        rawText: String,
        tnText: String,
        language: String,
        languageContext: String,
        alreadyNormalized: Boolean,
        tokenization: TokenizationResult,
        tokenIds: LongArray,
    ) {
        val tokenText = tokenization.tokens.joinToString(" ")
        val tokenIdText = tokenIds.joinToString(" ")
        logChunked(
            METRIC_TAG,
            buildString {
                append("trace=").append(traceId)
                append(" alreadyNormalized=").append(alreadyNormalized)
                append(" language=").append(language)
                append(" languageContext=").append(languageContext)
                append(" rawLen=").append(rawText.length)
                append(" tnLen=").append(tnText.length)
                append(" normalizedLen=").append(tokenization.normalizedText.length)
                append(" tokenCount=").append(tokenization.tokens.size)
                append(" rawText=").append(rawText)
                append(" | tnText=").append(tnText)
                append(" | frontendInput=").append(tokenization.inputText)
                append(" | preprocessedText=").append(tokenization.preprocessedText)
                append(" | normalizedText=").append(tokenization.normalizedText)
                append(" | cleanedTokens=").append(tokenText)
                append(" | tokenIds=").append(tokenIdText)
            },
        )
    }

    private fun logDetail(traceId: Long, message: String) {
        logChunked(DETAIL_TAG, "trace=$traceId $message")
    }

    private fun logChunked(tag: String, message: String) {
        if (message.length <= LOG_CHUNK_SIZE) {
            runCatching { Log.i(tag, message) }
            return
        }
        var start = 0
        var part = 1
        val total = (message.length + LOG_CHUNK_SIZE - 1) / LOG_CHUNK_SIZE
        while (start < message.length) {
            val end = minOf(start + LOG_CHUNK_SIZE, message.length)
            runCatching { Log.i(tag, "part=$part/$total ${message.substring(start, end)}") }
            start = end
            part += 1
        }
    }

    @Suppress("UNUSED_PARAMETER")
    fun splitForStreaming(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String = "zh-en",
        languageContext: String = "zh-en",
        wordsPerSegment: Int = 7,
    ): List<String> {
        val tnText = LitsTnNormalizer.normalize(layout, text, language, languageContext)
        val normalized = normalizeText(preprocessZhMixedInput(tnText), languageContext).trim()
        if (normalized.isEmpty()) return emptyList()
        val segments = mutableListOf<String>()
        val current = StringBuilder()
        var index = 0
        fun flushCurrentSegment() {
            flushSegment(segments, current)
        }
        while (index < normalized.length) {
            val char = normalized[index]
            if (char.isWhitespace()) {
                if (current.isNotEmpty() && current.last() != ' ') current.append(' ')
                index += 1
                continue
            }
            current.append(char)
            if (shouldSplitAfterPunctuation(normalized, index, current, wordsPerSegment)) {
                while (index + 1 < normalized.length && isAttachedSentenceSuffix(normalized[index + 1])) {
                    index += 1
                    current.append(normalized[index])
                }
                while (
                    index + 1 < normalized.length &&
                    isSentenceEndPunctuation(normalized[index + 1]) &&
                    normalized[index + 1] != ','
                ) {
                    index += 1
                    current.append(normalized[index])
                }
                flushCurrentSegment()
            }
            index += 1
        }
        flushSegment(segments, current)
        return segments.ifEmpty { listOf(normalized) }
    }

    fun splitRawForStreaming(
        text: String,
        wordsPerSegment: Int = 7,
        maxCharsPerSegment: Int = 50,
    ): List<String> {
        val normalized = text.trim()
        if (normalized.isEmpty()) return emptyList()
        val segmentLimit = maxCharsPerSegment.coerceAtLeast(1)
        val segments = mutableListOf<String>()
        val current = StringBuilder()
        var index = 0
        fun flushCurrentSegment() {
            flushSegment(segments, current)
        }
        while (index < normalized.length) {
            val char = normalized[index]
            if (char.isWhitespace()) {
                if (current.isNotEmpty() && current.last() != ' ') current.append(' ')
                index += 1
                continue
            }
            current.append(char)
            if (shouldSplitRawAfterPunctuation(normalized, index, current, wordsPerSegment)) {
                while (index + 1 < normalized.length && isAttachedSentenceSuffix(normalized[index + 1])) {
                    index += 1
                    current.append(normalized[index])
                }
                flushCurrentSegment()
            } else if (current.length >= segmentLimit) {
                flushCurrentSegment()
            }
            index += 1
        }
        flushSegment(segments, current)
        return segments.ifEmpty { listOf(normalized) }
    }

    private fun shouldSplitRawAfterPunctuation(
        text: String,
        index: Int,
        current: StringBuilder,
        minWordsForWeakSplit: Int,
    ): Boolean {
        val char = text[index]
        if (!isRawSentenceEndPunctuation(char)) return false
        if (isPunctuationInsideTechnicalToken(text, index)) return false
        if (wouldCreateShortSymbolSegment(current)) return false
        if ((char == ',' || char == '\uFF0C' || char == '\u3001') &&
            !shouldSplitAfterWeakComma(text, index, current, minWordsForWeakSplit)
        ) {
            return false
        }
        if ((char == '.' || char == '\u3002') && !shouldSplitAfterPeriod(text, index)) return false
        return true
    }

    private fun isRawSentenceEndPunctuation(char: Char): Boolean =
        char == '.' || char == '!' || char == '?' || char == ';' || char == ',' ||
            char == '\u3002' || char == '\uFF01' || char == '\uFF1F' ||
            char == '\uFF1B' || char == '\uFF0C' || char == '\u3001' ||
            char == '\u2026'

    private fun shouldSplitAfterPunctuation(
        text: String,
        index: Int,
        current: StringBuilder,
        minWordsForWeakSplit: Int,
    ): Boolean {
        val char = text[index]
        if (!isSentenceEndPunctuation(char)) return false
        if (isPunctuationInsideTechnicalToken(text, index)) return false
        if (wouldCreateShortSymbolSegment(current)) return false
        if (char == ',' && !shouldSplitAfterWeakComma(text, index, current, minWordsForWeakSplit)) return false
        if (char == '.' && !shouldSplitAfterPeriod(text, index)) return false
        return true
    }

    private fun shouldSplitAfterPeriod(text: String, index: Int): Boolean {
        val prev = previousNonSpace(text, index - 1)
        val next = nextNonSpace(text, index + 1)
        if (prev != null && next != null && prev.isDigit() && next.isDigit()) return false
        if (isUrlOrEmailPeriod(text, index)) return false
        if (isEnglishAbbreviationPeriod(text, index)) return false
        if (prev != null && isHanzi(prev)) return true
        return isBoundaryAfterSentencePunctuation(text, index)
    }

    private fun shouldSplitAfterWeakComma(
        text: String,
        index: Int,
        current: StringBuilder,
        minWordsForWeakSplit: Int,
    ): Boolean {
        val prev = previousNonSpace(text, index - 1)
        val next = nextNonSpace(text, index + 1)
        if (prev != null && next != null && prev.isDigit() && next.isDigit()) return false
        val trimmed = current.toString().trim()
        if (trimmed.length < MIN_WEAK_PUNCTUATION_SEGMENT_CHARS) return false
        return countRoughWords(trimmed) >= minWordsForWeakSplit || trimmed.any(::isHanzi)
    }

    private fun isBoundaryAfterSentencePunctuation(text: String, index: Int): Boolean {
        var cursor = index + 1
        while (cursor < text.length && isAttachedSentenceSuffix(text[cursor])) {
            cursor += 1
        }
        return cursor >= text.length || text[cursor].isWhitespace() || isHanzi(text[cursor])
    }

    private fun isEnglishAbbreviationPeriod(text: String, index: Int): Boolean {
        val token = asciiTokenBefore(text, index).lowercase()
        if (token in ENGLISH_ABBREVIATIONS) return true
        if (token.length == 1 && token.single() in 'a'..'z') return true
        val prefix = text.substring(0, index + 1)
        return ACRONYM_AT_END_REGEX.containsMatchIn(prefix)
    }

    private fun isUrlOrEmailPeriod(text: String, index: Int): Boolean {
        val start = scanNonSpaceTokenStart(text, index)
        val end = scanNonSpaceTokenEnd(text, index)
        val token = text.substring(start, end)
        val nextIsAsciiAlnum = text.getOrNull(index + 1)?.let(::isAsciiAlnum) == true
        return (nextIsAsciiAlnum && ("://" in token || "@" in token || token.startsWith("www.", ignoreCase = true))) ||
            (index + 1 < text.length && isAsciiAlnum(text[index + 1]) && token.count { it == '.' } >= 1)
    }

    private fun isPunctuationInsideTechnicalToken(text: String, index: Int): Boolean {
        val char = text[index]
        val prev = text.getOrNull(index - 1)
        val next = text.getOrNull(index + 1)
        if (prev == null || next == null) return false
        if (prev.isDigit() && next.isDigit()) return true
        if ((char == ':' || char == '/' || char == '?' || char == '=' || char == '&') && hasAsciiNear(text, index)) return true
        if ((char == '.' || char == '-' || char == '_' || char == '#') && isAsciiAlnum(next)) return true
        return false
    }

    private fun hasAsciiNear(text: String, index: Int): Boolean {
        val start = scanNonSpaceTokenStart(text, index)
        val end = scanNonSpaceTokenEnd(text, index)
        return text.substring(start, end).any(::isAsciiAlnum)
    }

    private fun wouldCreateShortSymbolSegment(current: StringBuilder): Boolean {
        val trimmed = current.toString().trim()
        if (trimmed.length >= MIN_SHORT_SYMBOL_SEGMENT_CHARS) return false
        if (trimmed.any(::isHanzi) && trimmed.none(::isAsciiAlnum)) return false
        return true
    }

    private fun asciiTokenBefore(text: String, endExclusive: Int): String {
        var cursor = endExclusive - 1
        while (cursor >= 0 && text[cursor].isLetter()) {
            cursor -= 1
        }
        return text.substring(cursor + 1, endExclusive)
    }

    private fun scanNonSpaceTokenStart(text: String, index: Int): Int {
        var cursor = index
        while (cursor > 0 && !text[cursor - 1].isWhitespace()) {
            cursor -= 1
        }
        return cursor
    }

    private fun scanNonSpaceTokenEnd(text: String, index: Int): Int {
        var cursor = index + 1
        while (cursor < text.length && !text[cursor].isWhitespace()) {
            cursor += 1
        }
        return cursor
    }

    private fun previousNonSpace(text: String, start: Int): Char? {
        var cursor = start
        while (cursor >= 0) {
            if (!text[cursor].isWhitespace()) return text[cursor]
            cursor -= 1
        }
        return null
    }

    private fun nextNonSpace(text: String, start: Int): Char? {
        var cursor = start
        while (cursor < text.length) {
            if (!text[cursor].isWhitespace()) return text[cursor]
            cursor += 1
        }
        return null
    }

    private fun countRoughWords(text: String): Int {
        var count = 0
        var inAsciiWord = false
        for (char in text) {
            when {
                isHanzi(char) -> {
                    count += 1
                    inAsciiWord = false
                }
                char.isLetterOrDigit() -> {
                    if (!inAsciiWord) {
                        count += 1
                        inAsciiWord = true
                    }
                }
                else -> inAsciiWord = false
            }
        }
        return count
    }

    private fun tokenize(
        resources: FrontendResources,
        text: String,
        language: String,
        languageContext: String,
    ): List<String> = tokenizeDetailed(resources, text, language, languageContext, traceId = -1L).tokens

    private fun tokenizeDetailed(
        resources: FrontendResources,
        text: String,
        language: String,
        languageContext: String,
        traceId: Long,
    ): TokenizationResult {
        tokenizeArpabetInput(resources, text, traceId)?.let {
            return TokenizationResult(
                inputText = text,
                preprocessedText = text,
                normalizedText = text,
                tokens = it,
            )
        }
        val preprocessed = resources.frontendRules.apply("pre_frontend", preprocessZhMixedInput(text))
        val normalizedText = normalizeText(preprocessed, languageContext)
        val normalized = normalizeTechnicalText(resources, normalizedText, languageContext).trim()
        if (normalized.isEmpty()) {
            throw unsupported("text must not be empty after trim")
        }
        if (language == "en-US" && normalized.any(::isHanzi)) {
            throw unsupported("en-US mode does not support Chinese input")
        }
        if (traceId > 0L) {
            logDetail(
                traceId,
                "stage input='$text' preprocessed='$preprocessed' normalizedText='$normalizedText' technicalNormalized='$normalized'",
            )
        }
        val output = mutableListOf<String>()
        var index = 0
        while (index < normalized.length) {
            val char = normalized[index]
            if (languageContext == "zh-en" && isAsciiAlnum(char)) {
                val end = scanAsciiAlnumRun(normalized, index)
                val run = normalized.substring(index, end)
                if (shouldExpandPlateAlnumRun(run)) {
                    appendPlateAlnumRun(output, resources, run, traceId)
                    index = end
                    continue
                }
            }
            when {
                char.isWhitespace() -> {
                    appendBoundary(output)
                    index += 1
                }

                isPunctuationChar(char) -> {
                    appendPunctuation(output, char.toString())
                    index += 1
                }

                char.isDigit() -> {
                    val end = scanDigits(normalized, index)
                    val digits = normalized.substring(index, end)
                    if (languageContext == "zh-en") {
                        val chineseText = digits.map { chineseDigitTextByChar.getValue(it) }.joinToString("")
                        val pinyin = hanziChunkToPinyin(resources, chineseText)
                        val sandhi = applyThirdToneSandhi(pinyin)
                        if (traceId > 0L) {
                            logDetail(
                                traceId,
                                "digits.zh digits='$digits' hanzi='$chineseText' pinyin='${pinyin.joinToString(" ")}' sandhi='${sandhi.joinToString(" ")}'",
                            )
                        }
                        appendChineseSyllables(
                            output,
                            resources,
                            sandhi,
                            trimLeadingBoundary = !shouldKeepBoundaryBeforeChinese(normalized, index),
                        )
                    } else {
                        digits.forEach { digit ->
                            appendBoundary(output)
                            val phones = resources.cmudict[englishDigitWordByChar.getValue(digit)]
                                ?: throw unsupported("english digit is not covered by cmudict.txt: $digit")
                            val tokens = arpabetToTokens(resources, phones)
                            if (traceId > 0L) {
                                logDetail(
                                    traceId,
                                    "digits.en digit='$digit' word='${englishDigitWordByChar.getValue(digit)}' phones='${phones.joinToString(" ")}' tokens='${tokens.joinToString(" ")}'",
                                )
                            }
                            output += tokens
                        }
                        appendBoundary(output)
                    }
                    index = end
                }

                isHanzi(char) -> {
                    val end = scanHanziChunk(normalized, index)
                    val hanziText = normalized.substring(index, end)
                    val pinyin = hanziChunkToPinyin(resources, hanziText)
                    val sandhi = restoreOverridePinyin(resources, hanziText, applyMandarinToneSandhi(hanziText, pinyin))
                    if (traceId > 0L) {
                        logDetail(
                            traceId,
                            "hanzi chunk='$hanziText' pinyin='${pinyin.joinToString(" ")}' sandhi='${sandhi.joinToString(" ")}'",
                        )
                    }
                    appendChineseSyllables(
                        output,
                        resources,
                        sandhi,
                        trimLeadingBoundary = !shouldKeepBoundaryBeforeChinese(normalized, index),
                    )
                    index = end
                }

                char.isLowerCase() -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end > index && end < normalized.length && normalized[end].isDigit()) {
                        val candidate = normalized.substring(index, end + 1)
                        val tokens = resources.pinyinToTokens[candidate]
                        if (tokens != null) {
                            if (traceId > 0L) {
                                logDetail(traceId, "ascii.zh-token candidate='$candidate' tokens='${tokens.joinToString(" ")}'")
                            }
                            while (output.lastOrNull() == "_") {
                                output.removeAt(output.lastIndex)
                            }
                            output += tokens
                            index = end + 1
                            continue
                        }
                    }
                    val actualEnd = if (end > index) end else throw unsupported("unsupported frontend character: $char")
                    val word = normalized.substring(index, actualEnd)
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(
                        resources,
                        word,
                        preferLetterName = shouldPreferLetterName(normalized, actualEnd, word),
                    )
                    val tokens = arpabetToTokens(resources, phones)
                    if (traceId > 0L) {
                        logDetail(traceId, "english word='$word' phones='${phones.joinToString(" ")}' tokens='${tokens.joinToString(" ")}'")
                    }
                    output += tokens
                    appendBoundary(output)
                    index = actualEnd
                }

                isEnglishLetter(char) -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end <= index) throw unsupported("unsupported frontend character: $char")
                    val word = normalized.substring(index, end)
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(
                        resources,
                        word,
                        preferLetterName = shouldPreferLetterName(normalized, end, word),
                    )
                    val tokens = arpabetToTokens(resources, phones)
                    if (traceId > 0L) {
                        logDetail(traceId, "english word='$word' phones='${phones.joinToString(" ")}' tokens='${tokens.joinToString(" ")}'")
                    }
                    output += tokens
                    appendBoundary(output)
                    index = end
                }

                else -> {
                    appendUnknownSymbol(output)
                    index += 1
                }
            }
        }
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        return TokenizationResult(
            inputText = text,
            preprocessedText = preprocessed,
            normalizedText = normalized,
            tokens = output,
        )
    }

    private fun shouldExpandPlateAlnumRun(run: String): Boolean =
        run.all { it.isDigit() } ||
            (run.any { it.isDigit() } && run.any { it in 'A'..'Z' }) ||
            (run.length == 1 && run.single() in 'A'..'Z')

    private fun appendPlateAlnumRun(
        output: MutableList<String>,
        resources: FrontendResources,
        run: String,
        traceId: Long,
    ) {
        var index = 0
        while (index < run.length) {
            val char = run[index]
            when {
                char.isDigit() -> {
                    val digitEnd = scanDigits(run, index)
                    val digits = run.substring(index, digitEnd)
                    val hanzi = digits.map { chineseDigitTextByChar.getValue(it) }.joinToString("")
                    val pinyin = hanziChunkToPinyin(resources, hanzi)
                    if (traceId > 0L) {
                        logDetail(traceId, "plate digits='$digits' hanzi='$hanzi' pinyin='${pinyin.joinToString(" ")}'")
                    }
                    appendChineseSyllables(
                        output,
                        resources,
                        pinyin,
                    )
                    index = digitEnd
                }

                isEnglishLetter(char) -> {
                    appendBoundary(output)
                    val phones = letterPhonesByChar[char.uppercaseChar()]
                        ?: throw unsupported("ASCII letter is not supported by plate frontend: $char")
                    val tokens = arpabetToTokens(
                        resources,
                        phones,
                    )
                    if (traceId > 0L) {
                        logDetail(traceId, "plate letter='$char' phones='${phones.joinToString(" ")}' tokens='${tokens.joinToString(" ")}'")
                    }
                    output += tokens
                    appendBoundary(output)
                    index += 1
                }

                else -> index += 1
            }
        }
    }

    private fun normalizeText(text: String, languageContext: String = "zh-en"): String {
        var normalized = text.replace("...", "\u2026")
            .replace("\u22EF", "\u2026")
            .replace("\u00B7\u00B7\u00B7", "\u2026")
            .replace("\u30FB\u30FB\u30FB", "\u2026")
        normalized = Normalizer.normalize(normalized, Normalizer.Form.NFKC)
        normalized = normalized.replace("...", "\u2026")
            .replace("\u22EF", "\u2026")
            .replace("\u00B7\u00B7\u00B7", "\u2026")
            .replace("\u30FB\u30FB\u30FB", "\u2026")
        val output = StringBuilder(normalized.length)
        var index = 0
        while (index < normalized.length) {
            val code = normalized[index].code
            if (isHighSurrogate(code)) {
                if (index + 1 < normalized.length && isLowSurrogate(normalized[index + 1].code)) {
                    index += 1
                }
                output.append(',')
                index += 1
                continue
            }
            if (isLowSurrogate(code) || isIgnoredFormatCode(code)) {
                index += 1
                continue
            }
            output.append(normalizeFrontendChar(normalized[index], languageContext))
            index += 1
        }
        return output.toString()
    }

    private fun normalizeFrontendChar(char: Char, languageContext: String): String {
        fullwidthPunctuation[char]?.let { return it }
        if (isSupportedFrontendChar(char)) return char.toString()
        if (isAsciiSymbol(char)) return char.toString()
        if (languageContext != "en-US") {
            zhEnFrontendCharReplacements[char]?.let { return it }
            zhEnAsciiSymbolText[char]?.let { return it }
        }
        symbolToSafePunctuation[char]?.let { return it }
        if (isAsciiSymbol(char) || isUnicodeSymbolLike(char)) return ","
        return ","
    }

    private fun normalizeTechnicalText(resources: FrontendResources, text: String, languageContext: String): String {
        var normalized = resources.frontendRules.apply("post_frontend", text)
        if (languageContext == "en-US") {
            return normalizeResidualSymbols(normalized, languageContext)
        }
        normalized = percentNumberRegex.replace(normalized) { match ->
            "百分之${numberTextToHanzi(match.groupValues[1])}"
        }
        normalized = normalized.replace(Regex("\\b(?:dot|point)\\b", RegexOption.IGNORE_CASE), "点")
        normalized = normalized.replace(Regex("\\bunderscore\\b", RegexOption.IGNORE_CASE), "下划线")
        normalized = versionNumberWithSuffixRegex.replace(normalized) { match ->
            match.value.split('.').joinToString("点", transform = ::numberTextToHanzi)
        }
        normalized = digitDotRegex.replace(normalized, "点")
        normalized = hanziDigitDotRegex.replace(normalized, "点")
        normalized = leadingDotAsciiTokenRegex.replace(normalized, "点")
        normalized = caretPowerTwoRegex.replace(normalized, "平方")
        normalized = normalized.replace("=", "等于")
        normalized = urlSchemeSeparatorRegex.replace(normalized) { match ->
            "${match.groupValues[1]}冒号斜杠斜杠"
        }
        normalized = technicalAsciiTokenRegex.replace(normalized) { match ->
            val token = match.groupValues[1]
            if (looksLikeIpv6(token) || token.none { it in technicalSymbolReadings }) {
                token
            } else {
                buildString {
                    token.forEach { char ->
                        append(technicalSymbolReadings[char] ?: char)
                    }
                }
            }
        }
        return normalizeResidualSymbols(normalized, languageContext)
    }

    private fun normalizeResidualSymbols(text: String, languageContext: String): String {
        val output = StringBuilder(text.length)
        var index = 0
        while (index < text.length) {
            val code = text[index].code
            if (isHighSurrogate(code)) {
                if (index + 1 < text.length && isLowSurrogate(text[index + 1].code)) {
                    index += 1
                }
                output.append(',')
                index += 1
                continue
            }
            if (isLowSurrogate(code) || isIgnoredFormatCode(code)) {
                index += 1
                continue
            }
            val char = text[index]
            if (isSupportedFrontendChar(char)) {
                output.append(char)
            } else if (languageContext != "en-US") {
                output.append(
                    zhEnFrontendCharReplacements[char]
                        ?: zhEnAsciiSymbolText[char]
                        ?: symbolToSafePunctuation[char]
                        ?: ",",
                )
            } else {
                output.append(symbolToSafePunctuation[char] ?: ",")
            }
            index += 1
        }
        return output.toString()
    }

    private fun preprocessZhMixedInput(text: String): String {
        var normalized = commaIntegerCurrencyRegex.replace(text) { match ->
            compactIntegerCurrencyWithCommas(match.groupValues[1])
        }
        normalized = thousandsSeparatorRegex.replace(normalized, "")
        normalized = negativeTemperatureRangeRegex.replace(normalized) { match ->
            "${match.groupValues[1]}零下${numberTextToHanzi(match.groupValues[2])}到${numberTextToHanzi(match.groupValues[3])}${match.groupValues[4]}"
        }
        normalized = negativeTemperatureRegex.replace(normalized) { match ->
            "${match.groupValues[1]}零下${numberTextToHanzi(match.groupValues[2])}${match.groupValues[3]}"
        }
        normalized = clockMinuteLeadingZeroRegex.replace(normalized) { match ->
            "${numberTextToHanzi(match.groupValues[1])}点零${numberTextToHanzi(match.groupValues[2])}分"
        }
        normalized = hanziClockMinuteLeadingZeroRegex.replace(normalized) { match ->
            "${match.groupValues[1]}点零${chineseDigitTextByChar.getValue(match.groupValues[2].single())}分"
        }
        normalized = durationMinuteLeadingZeroRegex.replace(normalized) { match ->
            "${numberTextToHanzi(match.groupValues[1])}小时零${numberTextToHanzi(match.groupValues[2])}分钟"
        }
        normalized = yearMonthLeadingZeroRegex.replace(normalized) { match ->
            "${match.groupValues[1]}零${numberTextToHanzi(match.groupValues[2])}月"
        }
        normalized = yearMonthRegex.replace(normalized) { match ->
            "${match.groupValues[1]}${numberTextToHanzi(match.groupValues[2])}月"
        }
        normalized = monthDayLeadingZeroRegex.replace(normalized) { match ->
            "${match.groupValues[1]}零${numberTextToHanzi(match.groupValues[2])}日"
        }
        normalized = monthDayRegex.replace(normalized) { match ->
            "${match.groupValues[1]}${numberTextToHanzi(match.groupValues[2])}${match.groupValues[3]}"
        }
        normalized = vinCodeRegex.replace(normalized) { match ->
            match.groupValues[1] + normalizeSerialCode(match.groupValues[2])
        }
        normalized = productCodeRegex.replace(normalized) { match ->
            match.groupValues[1] + normalizeSerialCode(match.groupValues[2]) + match.groupValues[3]
        }
        normalized = serialCodeRegex.replace(normalized) { match ->
            match.groupValues[1] + match.groupValues[2] + normalizeSerialCode(match.groupValues[3])
        }
        return normalized
    }

    private fun normalizeSerialCode(code: String): String = buildString {
        code.forEach { char ->
            append(chineseDigitTextByChar[char] ?: char)
        }
    }

    private fun compactIntegerCurrencyWithCommas(text: String): String {
        val value = text.replace(",", "").toLongOrNull() ?: return text.replace(",", "")
        return when {
            value >= 100_000_000L && value % 100_000_000L == 0L -> integerTextToHanzi((value / 100_000_000L).toString()) + "亿"
            value >= 10_000L && value % 10_000L == 0L -> integerTextToHanzi((value / 10_000L).toString()) + "万"
            else -> value.toString()
        }
    }

    private fun looksLikeIpv6(token: String): Boolean =
        token.count { it == ':' } >= 2 && token.all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' || it == ':' }

    private fun numberTextToHanzi(text: String): String {
        val parts = text.split('.', limit = 2)
        val integer = integerTextToHanzi(parts[0])
        if (parts.size == 1) return integer
        return integer + "点" + parts[1].map { chineseDigitTextByChar.getValue(it) }.joinToString("")
    }

    private fun integerTextToHanzi(text: String): String {
        val value = text.toIntOrNull() ?: return text.map { chineseDigitTextByChar.getValue(it) }.joinToString("")
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

    private fun flushSegment(segments: MutableList<String>, current: StringBuilder) {
        current.trimTrailingSpace()
        val segment = current.toString().trim()
        if (segment.isNotEmpty()) {
            segments += segment
        }
        current.clear()
    }

    private fun StringBuilder.trimTrailingSpace() {
        while (isNotEmpty() && last().isWhitespace()) {
            deleteCharAt(lastIndex)
        }
    }

    private fun nextNonSpaceIsPunctuation(text: String, start: Int): Boolean {
        var index = start
        while (index < text.length && text[index].isWhitespace()) {
            index += 1
        }
        return index < text.length && isPunctuationChar(text[index])
    }

    private fun hanziChunkToPinyin(resources: FrontendResources, text: String): List<String> {
        val output = mutableListOf<String>()
        var index = 0
        while (index < text.length) {
            val word = longestWord(resources, text, index)
            output += lexiconPinyinForWord(resources, word)
            index += word.length
        }
        return output
    }

    private fun longestWord(resources: FrontendResources, text: String, start: Int): String {
        resources.overrideWordPinyin.keys
            .filter { it.length > 1 && text.startsWith(it, start) }
            .maxByOrNull { it.length }
            ?.let { return it }
        val maxLength = minOf(resources.maxWordLength, text.length - start)
        for (length in maxLength downTo 2) {
            val candidate = text.substring(start, start + length)
            if (resources.overrideWordPinyin.containsKey(candidate) || resources.wordPinyin.containsKey(candidate)) {
                return candidate
            }
        }
        return text[start].toString()
    }

    private fun lexiconPinyinForWord(resources: FrontendResources, word: String): List<String> {
        resources.overrideWordPinyin[word]?.let { pinyin ->
            val syllables = normalizeLexiconPinyin(pinyin)
            if (syllables.isNotEmpty()) return syllables
        }
        val direct = resources.wordPinyin[word]
        if (direct != null && word !in resources.polyphonicWords) {
            val syllables = normalizeLexiconPinyin(direct)
            if (syllables.isNotEmpty()) return syllables
        }
        val output = mutableListOf<String>()
        for (char in word) {
            val pinyin = resources.wordPinyin[char.toString()]
            if (pinyin == null) {
                output += ","
                continue
            }
            val syllables = normalizeLexiconPinyin(pinyin)
            if (syllables.isEmpty()) {
                output += ","
                continue
            }
            output += syllables
        }
        return output
    }

    private fun normalizeLexiconPinyin(text: String): List<String> = text
        .trim()
        .split(Regex("\\s+"))
        .map { it.replace('\u7709', 'v').replace('\u813A', 'v') }
        .filter { pinyinSyllableRegex.matches(it) }

    private fun applyMandarinToneSandhi(text: String, tokens: List<String>): List<String> {
        val output = applyThirdToneSandhi(tokens).toMutableList()
        if (text.length != output.size) return output
        if (text.length > 1 && text.all { it in CHINESE_DIGIT_SEQUENCE_CHARS }) return output
        applyBuSandhi(text, output)
        applyYiSandhi(text, output)
        applyErSandhi(text, output)
        return output
    }

    private fun restoreOverridePinyin(resources: FrontendResources, text: String, tokens: List<String>): List<String> {
        if (text.length != tokens.size || resources.overrideWordPinyin.isEmpty()) return tokens
        val output = tokens.toMutableList()
        val occupied = BooleanArray(output.size)
        resources.overrideWordPinyin.entries
            .filter { it.key.length > 1 }
            .sortedByDescending { it.key.length }
            .forEach { (word, pinyin) ->
                val syllables = normalizeLexiconPinyin(pinyin)
                if (syllables.size != word.length) return@forEach
                var start = text.indexOf(word)
                while (start >= 0) {
                    val end = start + word.length
                    if ((start until end).none { occupied[it] }) {
                        for (offset in syllables.indices) {
                            output[start + offset] = syllables[offset]
                            occupied[start + offset] = true
                        }
                    }
                    start = text.indexOf(word, start + 1)
                }
            }
        return output
    }

    private fun applyBuSandhi(text: String, tokens: MutableList<String>) {
        if (text.all { it == '不' }) return
        if (text == "不字") return
        if (text.length == 3 && text[1] == '不' && tokens.getOrNull(1)?.startsWith("bu") == true) {
            tokens[1] = changePinyinTone(tokens[1], '5')
            return
        }
        text.forEachIndexed { index, char ->
            if (char == '不' && tokens.getOrNull(index + 1)?.lastOrNull() == '4') {
                tokens[index] = changePinyinTone(tokens[index], '2')
            }
        }
    }

    private fun applyYiSandhi(text: String, tokens: MutableList<String>) {
        if (text.length == 3 && text[1] == '一' && text[0] == text[2]) {
            tokens[1] = changePinyinTone(tokens[1], '5')
            return
        }
        if (text.startsWith("第一") && tokens.size > 1) {
            tokens[1] = changePinyinTone(tokens[1], '1')
        }
        if (text.startsWith("一月") || text.startsWith("一日") || text.startsWith("一号")) {
            tokens[0] = changePinyinTone(tokens[0], '1')
        }
        text.forEachIndexed { index, char ->
            if (char != '一' || index + 1 >= text.length || text.getOrNull(index - 1) == '第') return@forEachIndexed
            val current = tokens.getOrNull(index)
            val next = tokens.getOrNull(index + 1)
            if (current == null || next == null || !pinyinSyllableRegex.matches(current) || !pinyinSyllableRegex.matches(next)) {
                return@forEachIndexed
            }
            tokens[index] = changePinyinTone(current, if (next.last() == '4') '2' else '4')
        }
    }

    private fun applyErSandhi(text: String, tokens: MutableList<String>) {
        if (text.length > 1 && text.last() == '儿' && tokens.lastOrNull()?.startsWith("er") == true) {
            tokens[tokens.lastIndex] = changePinyinTone(tokens.last(), '5')
        }
    }

    private fun changePinyinTone(syllable: String, tone: Char): String =
        if (pinyinSyllableRegex.matches(syllable)) syllable.dropLast(1) + tone else syllable

    private fun applyThirdToneSandhi(tokens: List<String>): List<String> {
        val output = tokens.toMutableList()
        val pinyinIndices = output.indices.filter { pinyinSyllableRegex.matches(output[it]) }
        for (position in 0 until pinyinIndices.lastIndex) {
            val current = pinyinIndices[position]
            val next = pinyinIndices[position + 1]
            if (output[current].last() == '3' && output[next].last() == '3') {
                output[current] = output[current].dropLast(1) + "2"
            }
        }
        return output
    }

    private fun phonesForEnglishWord(
        resources: FrontendResources,
        rawWord: String,
        preferLetterName: Boolean = false,
    ): List<String> {
        val normalized = rawWord.uppercase()
        if (preferLetterName && rawWord.length == 1) {
            letterPhonesByChar[normalized.single()]?.let { return it }
        }
        resources.supplementLexicon[normalized]?.let { return it }
        if (shouldSpellUppercaseWord(rawWord, normalized)) {
            val spelled = spellEnglishWord(resources, normalized)
            if (spelled.isNotEmpty()) return spelled
        }
        resources.englishLexicon[normalized]?.let { return it }
        if ('-' in normalized) {
            val output = mutableListOf<String>()
            for (part in normalized.split('-')) {
                if (part.isEmpty()) continue
                val phones = resources.englishLexicon[part]
                    ?: spellEnglishWord(resources, part)
                if (phones.isEmpty()) {
                    continue
                }
                output += phones
            }
            if (output.isNotEmpty()) return output
        }
        val spelled = spellEnglishWord(resources, normalized)
        if (spelled.isNotEmpty()) return spelled
        return emptyList()
    }

    private fun tokenizeArpabetInput(resources: FrontendResources, text: String, traceId: Long = -1L): List<String>? {
        val normalized = Normalizer.normalize(text, Normalizer.Form.NFKC)
            .replace("/", " / ")
            .replace("|", " | ")
            .replace("_", " _ ")
            .trim()
        if (normalized.isEmpty() || normalized.any(::isHanzi)) return null
        val parts = normalized.split(Regex("\\s+")).filter { it.isNotEmpty() }
        if (parts.isEmpty()) return null
        val output = mutableListOf<String>()
        var sawPhone = false
        var endedWithPunctuation = false
        for (part in parts) {
            val token = part.uppercase()
            when {
                part in arpabetBoundaryTokens -> {
                    appendBoundary(output)
                    endedWithPunctuation = false
                }
                part.length == 1 && isPunctuationChar(part.single()) -> {
                    appendPunctuation(output, part)
                    endedWithPunctuation = true
                }
                resources.arpabetToTokens.containsKey(token) -> {
                    val tokens = arpabetToTokens(resources, listOf(token))
                    if (traceId > 0L) {
                        logDetail(traceId, "arpabet passthrough phone='$token' tokens='${tokens.joinToString(" ")}'")
                    }
                    output += tokens
                    sawPhone = true
                    endedWithPunctuation = false
                }
                else -> return null
            }
        }
        if (sawPhone && !endedWithPunctuation) {
            appendPunctuation(output, ".")
        }
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        if (sawPhone && traceId > 0L) {
            logDetail(traceId, "arpabet passthrough input='$text' normalized='$normalized' tokens='${output.joinToString(" ")}'")
        }
        return if (sawPhone) output else null
    }

    private fun shouldSpellUppercaseWord(rawWord: String, normalized: String): Boolean =
        rawWord.length > 1 &&
            rawWord.all { it in 'A'..'Z' } &&
            normalized !in acronymWordReadings

    private fun shouldPreferLetterName(text: String, end: Int, word: String): Boolean {
        if (word.length != 1 || !isEnglishLetter(word.single())) return false
        if (word.uppercase() != "A") return true
        return !hasEnglishWordAfter(text, end)
    }

    private fun hasEnglishWordAfter(text: String, start: Int): Boolean {
        var index = start
        while (index < text.length) {
            if (isEnglishLetter(text[index])) return true
            index += 1
        }
        return false
    }

    private fun spellEnglishWord(resources: FrontendResources, word: String): List<String> {
        val output = mutableListOf<String>()
        for (char in word) {
            if (!isEnglishLetter(char)) continue
            val phones = letterPhonesByChar[char.uppercaseChar()]
                ?: resources.cmudict[char.toString()]
                ?: return emptyList()
            output += phones
        }
        return output
    }

    private fun arpabetToTokens(resources: FrontendResources, phones: List<String>): List<String> {
        val rawTokens = buildList {
            for (phone in phones) {
                val tokens = resources.arpabetToTokens[phone]
                    ?: continue
                addAll(tokens)
            }
        }
        return mergeEnglishTokens(rawTokens)
    }

    private fun mergeEnglishTokens(tokens: List<String>): List<String> {
        val output = mutableListOf<String>()
        var index = 0
        while (index < tokens.size) {
            var merged = false
            for ((pair, replacement) in englishMergeRules) {
                if (tokens.subList(index, minOf(index + pair.size, tokens.size)) == pair) {
                    output += replacement
                    index += pair.size
                    merged = true
                    break
                }
            }
            if (!merged) {
                output += tokens[index]
                index += 1
            }
        }
        return output
    }

    private fun appendBoundary(output: MutableList<String>) {
        if (output.isNotEmpty() && output.last() != "_") {
            output += "_"
        }
    }

    private fun appendPunctuation(output: MutableList<String>, token: String) {
        appendBoundary(output)
        output += token
        appendBoundary(output)
    }

    private fun appendUnknownSymbol(output: MutableList<String>) {
        if (output.lastOrNull() != ",") {
            appendPunctuation(output, ",")
        }
    }

    private fun appendChineseSyllables(
        output: MutableList<String>,
        resources: FrontendResources,
        syllables: List<String>,
        trimLeadingBoundary: Boolean = true,
    ) {
        while (trimLeadingBoundary && output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        syllables.forEach { syllable ->
            if (syllable == ",") {
                appendPunctuation(output, ",")
                return@forEach
            }
            val tokens = resources.pinyinToTokens[syllable]
            if (tokens == null) {
                appendPunctuation(output, ",")
                return@forEach
            }
            output += tokens
        }
    }

    private fun shouldKeepBoundaryBeforeChinese(text: String, index: Int): Boolean {
        val prev = previousNonSpace(text, index - 1)
        return prev != null && (isEnglishLetter(prev) || prev.isDigit() || isPunctuationChar(prev))
    }

    private fun intersperseZero(ids: List<Int>): LongArray {
        val output = LongArray(ids.size * 2 + 1)
        output[0] = 0L
        for (index in ids.indices) {
            output[index * 2 + 1] = ids[index].toLong()
            output[index * 2 + 2] = 0L
        }
        return output
    }

    private fun scanDigits(text: String, start: Int): Int {
        var index = start
        while (index < text.length && text[index].isDigit()) {
            index += 1
        }
        return index
    }

    private fun scanHanziChunk(text: String, start: Int): Int {
        var index = start
        while (index < text.length && isHanzi(text[index])) {
            index += 1
        }
        return index
    }

    private fun scanEnglishWord(text: String, start: Int): Int {
        var index = start
        while (index < text.length && isEnglishLetter(text[index])) {
            index += 1
        }
        while (index + 1 < text.length && (text[index] == '\'' || text[index] == '-') && isEnglishLetter(text[index + 1])) {
            index += 1
            while (index < text.length && isEnglishLetter(text[index])) {
                index += 1
            }
        }
        return index
    }

    private fun scanAsciiAlnumRun(text: String, start: Int): Int {
        var index = start
        while (index < text.length && isAsciiAlnum(text[index])) {
            index += 1
        }
        return index
    }

    private fun isHanzi(char: Char): Boolean = hanziRegex.matches(char.toString())

    private fun isEnglishLetter(char: Char): Boolean = char in 'a'..'z' || char in 'A'..'Z'

    private fun isAsciiAlnum(char: Char): Boolean = isEnglishLetter(char) || char.isDigit()

    private fun isPunctuationChar(char: Char): Boolean = char == '\u2026' || char in punctuation

    private fun isSupportedFrontendChar(char: Char): Boolean =
        char.isWhitespace() ||
            isPunctuationChar(char) ||
            char.isDigit() ||
            isEnglishLetter(char) ||
            isHanzi(char)

    private fun isAsciiSymbol(char: Char): Boolean =
        char.code in 0x21..0x7e && !char.isDigit() && !isEnglishLetter(char)

    private fun isUnicodeSymbolLike(char: Char): Boolean {
        val code = char.code
        return code in 0x2000..0x206f ||
            code in 0x20a0..0x27bf ||
            code in 0x2b00..0x2bff ||
            code in 0x3000..0x303f ||
            code in 0xfe10..0xfe6f ||
            code in 0xff00..0xffef
    }

    private fun isHighSurrogate(code: Int): Boolean = code in 0xd800..0xdbff

    private fun isLowSurrogate(code: Int): Boolean = code in 0xdc00..0xdfff

    private fun isIgnoredFormatCode(code: Int): Boolean =
        code == 0x200c ||
            code == 0x200d ||
            code == 0x20e3 ||
            code == 0xfe0e ||
            code == 0xfe0f

    private fun isSentenceEndPunctuation(char: Char): Boolean = char in sentenceEndPunctuation

    private fun isAttachedSentenceSuffix(char: Char): Boolean = char in attachedSentenceSuffix

    private fun resources(layout: LitsTtsAssetInstaller.InstalledLayout): FrontendResources =
        resourcesByRoot.getOrPut(layout.rootDir.absolutePath) {
            val executor = Executors.newFixedThreadPool(FRONTEND_LOAD_THREADS) { runnable ->
                Thread(runnable, "lits-tts-frontend-load").apply { isDaemon = true }
            }
            try {
                val wordPinyinFuture = executor.submit(Callable { loadWordPinyin(layout) })
                val overrideWordPinyinFuture = executor.submit(Callable { loadWordPinyinOverrides(layout) })
                val polyphonicWords = executor.submit(Callable {
                    layout.polychar.readLines(Charsets.UTF_8)
                        .map { it.trim() }
                        .filter { it.isNotEmpty() }
                        .toSet()
                })
                val cmudict = executor.submit(Callable { loadCmudict(layout) })
                val supplementLexicon = executor.submit(Callable { loadSupplementLexicon(layout) })
                val frontendRules = executor.submit(Callable { FrontendRuleSet.load(layout.frontendRules) })
                val symbolToId = executor.submit(Callable { loadSymbols(layout) })
                val pinyinToTokens = executor.submit(Callable { loadTokenMap(layout.pinyinToTokens, "pinyin_to_tokens") })
                val arpabetToTokens = executor.submit(Callable { loadTokenMap(layout.arpabetToTokens, "arpabet_to_tokens") })
                val wordPinyin = wordPinyinFuture.get()
                val overrideWordPinyin = overrideWordPinyinFuture.get()
                val baseCmudict = cmudict.get()
                val supplement = supplementLexicon.get()
                FrontendResources(
                    wordPinyin = wordPinyin,
                    overrideWordPinyin = overrideWordPinyin,
                    polyphonicWords = polyphonicWords.get(),
                    maxWordLength = (wordPinyin.keys + overrideWordPinyin.keys).maxOfOrNull { it.length } ?: 1,
                    cmudict = baseCmudict,
                    supplementLexicon = supplement,
                    englishLexicon = mergeEnglishLexicon(baseCmudict, supplement),
                    frontendRules = frontendRules.get(),
                    symbolToId = symbolToId.get(),
                    pinyinToTokens = pinyinToTokens.get(),
                    arpabetToTokens = arpabetToTokens.get(),
                )
            } finally {
                executor.shutdown()
            }
        }

    private fun mergeEnglishLexicon(
        cmudict: Map<String, List<String>>,
        supplement: Map<String, List<String>>,
    ): Map<String, List<String>> = buildMap(cmudict.size + supplement.size) {
        putAll(cmudict)
        supplement.forEach { (word, phones) ->
            putIfAbsent(word, phones)
        }
    }

    private fun loadSupplementLexicon(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, List<String>> {
        if (!layout.supplementLexicon.isFile) return emptyMap()
        val root = JSONObject(layout.supplementLexicon.readText(Charsets.UTF_8))
        val entries = root.optJSONObject("entries") ?: root
        return buildMap {
            val iterator = entries.keys()
            while (iterator.hasNext()) {
                val key = iterator.next().uppercase()
                val value = entries.get(key)
                val phones = when (value) {
                    is JSONArray -> value.toStringList()
                    is JSONObject -> value.optJSONArray("phones")?.toStringList().orEmpty()
                    is String -> value.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
                    else -> emptyList()
                }
                if (phones.isNotEmpty()) put(key, phones)
            }
        }
    }

    private fun loadWordPinyin(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> {
        val base = if (layout.chineseLexiconBin.isFile) {
            try {
                loadWordPinyinBin(layout.chineseLexiconBin)
            } catch (exception: Exception) {
                loadWordPinyinText(layout)
            }
        } else {
            loadWordPinyinText(layout)
        }
        return buildMap {
            putAll(base)
            mergeWordPinyinText(rootDir = layout.rootDir, relativePath = LitsTtsAssetRegistry.POLYPHONE_PHRASES)
            mergeWordPinyinText(rootDir = layout.rootDir, relativePath = LitsTtsAssetRegistry.CHINESE_SURNAME_LEXICON)
        }
    }

    private fun loadWordPinyinOverrides(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> =
        buildMap {
            mergeWordPinyinText(rootDir = layout.rootDir, relativePath = LitsTtsAssetRegistry.POLYPHONE_PHRASES)
            mergeWordPinyinText(rootDir = layout.rootDir, relativePath = LitsTtsAssetRegistry.CHINESE_SURNAME_LEXICON)
        }

    private fun MutableMap<String, String>.mergeWordPinyinText(rootDir: File, relativePath: String) {
        val file = rootDir.resolve(relativePath)
        if (!file.isFile) return
        file.forEachLine(Charsets.UTF_8) { line ->
            val trimmed = line.trim()
            if (trimmed.isEmpty() || trimmed.startsWith("#")) return@forEachLine
            val parts = trimmed.split('\t', limit = 2)
            if (parts.size == 2) {
                put(parts[0], parts[1])
            }
        }
    }

    private fun loadWordPinyinText(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> =
        buildMap {
            layout.chineseLexicon.forEachLine(Charsets.UTF_8) { line ->
                val parts = line.trim().split('\t')
                if (parts.size == 2) {
                    put(parts[0], parts[1])
                }
            }
        }

    private fun loadCmudict(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, List<String>> =
        if (layout.cmudictBin.isFile) {
            try {
                loadCmudictBin(layout.cmudictBin)
            } catch (exception: Exception) {
                loadCmudictText(layout)
            }
        } else {
            loadCmudictText(layout)
        }

    private fun loadCmudictText(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, List<String>> =
        buildMap {
            layout.cmudict.forEachLine(Charsets.UTF_8) { line ->
                val trimmed = line.trim()
                if (trimmed.isEmpty()) return@forEachLine
                val parts = trimmed.split('\t', limit = 2)
                if (parts.size != 2) return@forEachLine
                val key = parts[0].substringBefore('(').uppercase()
                if (containsKey(key)) return@forEachLine
                val phones = parts[1].trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
                if (phones.isNotEmpty()) {
                    put(key, phones)
                }
            }
        }

    private fun loadWordPinyinBin(file: File): Map<String, String> =
        BinaryReader(file.readBytes()).let { input ->
            require(input.readInt() == WORD_PINYIN_BIN_MAGIC) { "invalid chinese lexicon bin magic" }
            val count = input.readInt()
            buildMap(count) {
                repeat(count) {
                    put(input.readUtf8String(), input.readUtf8String())
                }
            }
        }

    private fun loadCmudictBin(file: File): Map<String, List<String>> =
        BinaryReader(file.readBytes()).let { input ->
            require(input.readInt() == CMUDICT_BIN_MAGIC) { "invalid cmudict bin magic" }
            val count = input.readInt()
            buildMap(count) {
                repeat(count) {
                    val key = input.readUtf8String()
                    val phones = List(input.readInt()) { input.readUtf8String() }
                    put(key, phones)
                }
            }
        }

    private class BinaryReader(private val bytes: ByteArray) {
        private var offset: Int = 0

        fun readInt(): Int {
            require(offset + Int.SIZE_BYTES <= bytes.size) { "unexpected end of frontend bin" }
            val value = ((bytes[offset].toInt() and 0xff) shl 24) or
                ((bytes[offset + 1].toInt() and 0xff) shl 16) or
                ((bytes[offset + 2].toInt() and 0xff) shl 8) or
                (bytes[offset + 3].toInt() and 0xff)
            offset += Int.SIZE_BYTES
            return value
        }

        fun readUtf8String(): String {
            val length = readInt()
            require(length >= 0 && offset + length <= bytes.size) { "invalid frontend bin string length" }
            return bytes.decodeToString(offset, offset + length).also {
                offset += length
            }
        }
    }

    private fun loadSymbols(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, Int> {
        val symbols = JSONObject(layout.symbols.readText(Charsets.UTF_8)).getJSONArray("symbols")
        return buildMap {
            for (index in 0 until symbols.length()) {
                put(symbols.getString(index), index)
            }
        }
    }

    private fun loadTokenMap(file: java.io.File, key: String): Map<String, List<String>> {
        val root = JSONObject(file.readText(Charsets.UTF_8))
        val payload = root.getJSONObject(key)
        return buildMap {
            val iterator = payload.keys()
            while (iterator.hasNext()) {
                val name = iterator.next()
                val values = payload.getJSONArray(name)
                put(name, values.toStringList())
            }
        }
    }

    private fun JSONArray.toStringList(): List<String> = buildList {
        for (index in 0 until length()) {
            add(getString(index))
        }
    }

    private fun unsupported(message: String): IllegalStateException =
        IllegalStateException("${TtsErrorCode.RUNTIME_EXCEPTION}:$message")

    private data class FrontendResources(
        val wordPinyin: Map<String, String>,
        val overrideWordPinyin: Map<String, String>,
        val polyphonicWords: Set<String>,
        val maxWordLength: Int,
        val cmudict: Map<String, List<String>>,
        val supplementLexicon: Map<String, List<String>>,
        val englishLexicon: Map<String, List<String>>,
        val frontendRules: FrontendRuleSet,
        val symbolToId: Map<String, Int>,
        val pinyinToTokens: Map<String, List<String>>,
        val arpabetToTokens: Map<String, List<String>>,
    )

    private const val FRONTEND_LOAD_THREADS = 4
    private const val WORD_PINYIN_BIN_MAGIC = 0x4C505931
    private const val CMUDICT_BIN_MAGIC = 0x434D4431
}
