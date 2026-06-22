package com.lits.tts.sdk.internal

import com.lits.tts.sdk.TtsErrorCode
import java.io.File
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsFrontend {
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
        val resources = resources(layout)
        val rawTokens = tokenize(resources, text, language, languageContext)
        val ids = rawTokens.map { token ->
            resources.symbolToId[token] ?: throw unsupported("frontend token is not in zh_en_symbols.json: $token")
        }
        return ids.map { it.toLong() }.toLongArray()
    }

    fun preload(layout: LitsTtsAssetInstaller.InstalledLayout) {
        resources(layout)
    }

    @Suppress("UNUSED_PARAMETER")
    fun splitForStreaming(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        wordsPerSegment: Int = 7,
    ): List<String> {
        val normalized = normalizeText(text).trim()
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

    private fun shouldSplitAfterPunctuation(
        text: String,
        index: Int,
        current: StringBuilder,
        minWordsForWeakSplit: Int,
    ): Boolean {
        val char = text[index]
        if (!isSentenceEndPunctuation(char)) return false
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
        return "://" in token || "@" in token || token.startsWith("www.", ignoreCase = true) ||
            (index + 1 < text.length && isAsciiAlnum(text[index + 1]) && token.count { it == '.' } >= 1)
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
    ): List<String> {
        val normalized = normalizeText(text).trim()
        if (normalized.isEmpty()) {
            throw unsupported("text must not be empty after trim")
        }
        if (language == "en-US" && normalized.any(::isHanzi)) {
            throw unsupported("en-US mode does not support Chinese input")
        }
        val output = mutableListOf<String>()
        var index = 0
        while (index < normalized.length) {
            val char = normalized[index]
            if (languageContext == "zh-en" && isAsciiAlnum(char)) {
                val end = scanAsciiAlnumRun(normalized, index)
                val run = normalized.substring(index, end)
                if (shouldExpandPlateAlnumRun(run)) {
                    appendPlateAlnumRun(output, resources, run)
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
                        appendChineseSyllables(
                            output,
                            resources,
                            applyThirdToneSandhi(
                                hanziChunkToPinyin(
                                    resources,
                                    digits.map { chineseDigitTextByChar.getValue(it) }.joinToString(""),
                                ),
                            ),
                        )
                    } else {
                        digits.forEach { digit ->
                            appendBoundary(output)
                            val phones = resources.cmudict[englishDigitWordByChar.getValue(digit)]
                                ?: throw unsupported("english digit is not covered by cmudict.txt: $digit")
                            output += arpabetToTokens(resources, phones)
                        }
                        appendBoundary(output)
                    }
                    index = end
                }

                isHanzi(char) -> {
                    val end = scanHanziChunk(normalized, index)
                    appendChineseSyllables(
                        output,
                        resources,
                        applyThirdToneSandhi(
                            hanziChunkToPinyin(resources, normalized.substring(index, end)),
                        ),
                    )
                    index = end
                }

                char.isLowerCase() -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end > index && end < normalized.length && normalized[end].isDigit()) {
                        val candidate = normalized.substring(index, end + 1)
                        val tokens = resources.pinyinToTokens[candidate]
                        if (tokens != null) {
                            while (output.lastOrNull() == "_") {
                                output.removeAt(output.lastIndex)
                            }
                            output += tokens
                            index = end + 1
                            continue
                        }
                    }
                    val actualEnd = if (end > index) end else throw unsupported("unsupported frontend character: $char")
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(resources, normalized.substring(index, actualEnd))
                    output += arpabetToTokens(resources, phones)
                    appendBoundary(output)
                    index = actualEnd
                }

                isEnglishLetter(char) -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end <= index) throw unsupported("unsupported frontend character: $char")
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(resources, normalized.substring(index, end))
                    output += arpabetToTokens(resources, phones)
                    appendBoundary(output)
                    index = end
                }

                else -> throw unsupported("unsupported frontend character: $char")
            }
        }
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        return output
    }

    private fun shouldExpandPlateAlnumRun(run: String): Boolean =
        run.all { it.isDigit() } ||
            (run.any { it.isDigit() } && run.any { it in 'A'..'Z' }) ||
            (run.length == 1 && run.single() in 'A'..'Z')

    private fun appendPlateAlnumRun(
        output: MutableList<String>,
        resources: FrontendResources,
        run: String,
    ) {
        var index = 0
        while (index < run.length) {
            val char = run[index]
            when {
                char.isDigit() -> {
                    val digitEnd = scanDigits(run, index)
                    appendChineseSyllables(
                        output,
                        resources,
                        hanziChunkToPinyin(
                            resources,
                            run.substring(index, digitEnd).map { chineseDigitTextByChar.getValue(it) }.joinToString(""),
                        ),
                    )
                    index = digitEnd
                }

                isEnglishLetter(char) -> {
                    appendBoundary(output)
                    output += arpabetToTokens(
                        resources,
                        letterPhonesByChar[char.uppercaseChar()]
                            ?: throw unsupported("ASCII letter is not supported by plate frontend: $char"),
                    )
                    appendBoundary(output)
                    index += 1
                }

                else -> index += 1
            }
        }
    }

    private fun normalizeText(text: String): String {
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
        for (char in normalized) {
            output.append(fullwidthPunctuation[char] ?: char)
        }
        return output.toString()
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
        val maxLength = minOf(resources.maxWordLength, text.length - start)
        for (length in maxLength downTo 2) {
            val candidate = text.substring(start, start + length)
            if (resources.wordPinyin.containsKey(candidate)) {
                return candidate
            }
        }
        return text[start].toString()
    }

    private fun lexiconPinyinForWord(resources: FrontendResources, word: String): List<String> {
        val direct = resources.wordPinyin[word]
        if (direct != null && word !in resources.polyphonicWords) {
            val syllables = normalizeLexiconPinyin(direct)
            if (syllables.isNotEmpty()) return syllables
        }
        val output = mutableListOf<String>()
        for (char in word) {
            val pinyin = resources.wordPinyin[char.toString()]
                ?: throw unsupported("hanzi is not covered by chinese_lexicon.txt: $char")
            val syllables = normalizeLexiconPinyin(pinyin)
            if (syllables.isEmpty()) {
                throw unsupported("hanzi pinyin is invalid in chinese_lexicon.txt: $char")
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

    private fun phonesForEnglishWord(resources: FrontendResources, rawWord: String): List<String> {
        val normalized = rawWord.uppercase()
        resources.cmudict[normalized]?.let { return it }
        if ('-' in normalized) {
            val output = mutableListOf<String>()
            for (part in normalized.split('-')) {
                if (part.isEmpty()) continue
                val phones = resources.cmudict[part] ?: spellEnglishWord(resources, part)
                if (phones.isEmpty()) {
                    throw unsupported("english word is not covered by cmudict.txt: $rawWord")
                }
                output += phones
            }
            if (output.isNotEmpty()) return output
        }
        val spelled = spellEnglishWord(resources, normalized)
        if (spelled.isNotEmpty()) return spelled
        throw unsupported("english word is not covered by cmudict.txt: $rawWord")
    }

    private fun spellEnglishWord(resources: FrontendResources, word: String): List<String> {
        val output = mutableListOf<String>()
        for (char in word) {
            if (!isEnglishLetter(char)) continue
            val phones = resources.cmudict[char.toString()] ?: return emptyList()
            output += phones
        }
        return output
    }

    private fun arpabetToTokens(resources: FrontendResources, phones: List<String>): List<String> {
        val rawTokens = buildList {
            for (phone in phones) {
                val tokens = resources.arpabetToTokens[phone]
                    ?: throw unsupported("ARPAbet phone is not supported by Android frontend: $phone")
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
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        output += token
    }

    private fun appendChineseSyllables(
        output: MutableList<String>,
        resources: FrontendResources,
        syllables: List<String>,
    ) {
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        syllables.forEach { syllable ->
            output += resources.pinyinToTokens[syllable]
                ?: throw unsupported("pinyin is not covered by generated mapping: $syllable")
        }
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

    private fun isSentenceEndPunctuation(char: Char): Boolean = char in sentenceEndPunctuation

    private fun isAttachedSentenceSuffix(char: Char): Boolean = char in attachedSentenceSuffix

    private fun resources(layout: LitsTtsAssetInstaller.InstalledLayout): FrontendResources =
        resourcesByRoot.getOrPut(layout.rootDir.absolutePath) {
            val executor = Executors.newFixedThreadPool(FRONTEND_LOAD_THREADS) { runnable ->
                Thread(runnable, "lits-tts-frontend-load").apply { isDaemon = true }
            }
            try {
                val wordPinyinFuture = executor.submit(Callable { loadWordPinyin(layout) })
                val polyphonicWords = executor.submit(Callable {
                    layout.polychar.readLines(Charsets.UTF_8)
                        .map { it.trim() }
                        .filter { it.isNotEmpty() }
                        .toSet()
                })
                val cmudict = executor.submit(Callable { loadCmudict(layout) })
                val symbolToId = executor.submit(Callable { loadSymbols(layout) })
                val pinyinToTokens = executor.submit(Callable { loadTokenMap(layout.pinyinToTokens, "pinyin_to_tokens") })
                val arpabetToTokens = executor.submit(Callable { loadTokenMap(layout.arpabetToTokens, "arpabet_to_tokens") })
                val wordPinyin = wordPinyinFuture.get()
                FrontendResources(
                    wordPinyin = wordPinyin,
                    polyphonicWords = polyphonicWords.get(),
                    maxWordLength = wordPinyin.keys.maxOfOrNull { it.length } ?: 1,
                    cmudict = cmudict.get(),
                    symbolToId = symbolToId.get(),
                    pinyinToTokens = pinyinToTokens.get(),
                    arpabetToTokens = arpabetToTokens.get(),
                )
            } finally {
                executor.shutdown()
            }
        }

    private fun loadWordPinyin(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> =
        if (layout.chineseLexiconBin.isFile) {
            try {
                loadWordPinyinBin(layout.chineseLexiconBin)
            } catch (exception: Exception) {
                loadWordPinyinText(layout)
            }
        } else {
            loadWordPinyinText(layout)
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
        val polyphonicWords: Set<String>,
        val maxWordLength: Int,
        val cmudict: Map<String, List<String>>,
        val symbolToId: Map<String, Int>,
        val pinyinToTokens: Map<String, List<String>>,
        val arpabetToTokens: Map<String, List<String>>,
    )

    private const val FRONTEND_LOAD_THREADS = 4
    private const val WORD_PINYIN_BIN_MAGIC = 0x4C505931
    private const val CMUDICT_BIN_MAGIC = 0x434D4431
}
