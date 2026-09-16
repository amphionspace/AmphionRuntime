package com.lits.tts.sdk.internal

import java.io.File

/** Immutable UTF-8 dictionary: retains bytes and row offsets, not every decoded value. */
internal class CompactLexicon<V> private constructor(
    private val bytes: ByteArray,
    private val normalizeKey: (String) -> String,
    private val decodeValue: (String) -> V,
    private val firstWins: Boolean,
) : AbstractMap<String, V>() {
    private val offsets: IntArray
    override var size: Int = 0
        private set
    var maxKeyLength: Int = 0
        private set

    init {
        val lines = bytes.count { it == '\n'.code.toByte() } + 1
        var capacity = 2
        while (capacity < lines * 2L) capacity = Math.multiplyExact(capacity, 2)
        offsets = IntArray(capacity)
        var start = 0
        while (start < bytes.size) {
            val end = lineEnd(start)
            val tab = tabAt(start, end)
            if (tab > start && tab < end - 1) {
                val key = keyAt(start, tab)
                if (key.isNotEmpty()) {
                    var slot = slotFor(key)
                    while (offsets[slot] != 0 && keyAt(offsets[slot] - 1) != key) {
                        slot = (slot + 1) and (offsets.size - 1)
                    }
                    if (offsets[slot] == 0) {
                        size++
                        offsets[slot] = start + 1
                    } else if (!firstWins) offsets[slot] = start + 1
                    maxKeyLength = maxOf(maxKeyLength, key.length)
                }
            }
            start = end + 1
        }
    }

    override fun containsKey(key: String): Boolean = rowFor(key) >= 0

    override fun get(key: String): V? {
        val start = rowFor(key)
        return if (start < 0) null else valueAt(start)
    }

    private fun slotFor(key: String): Int {
        var hash = key.hashCode()
        hash = (hash xor (hash ushr 16)) * -2048144789
        hash = (hash xor (hash ushr 13)) * -1028477387
        return (hash xor (hash ushr 16)) and (offsets.size - 1)
    }

    private fun rowFor(key: String): Int {
        var slot = slotFor(key)
        while (offsets[slot] != 0) {
            val start = offsets[slot] - 1
            if (keyAt(start) == key) return start
            slot = (slot + 1) and (offsets.size - 1)
        }
        return -1
    }

    private fun lineEnd(start: Int): Int {
        var end = start
        while (end < bytes.size && bytes[end] != '\n'.code.toByte()) end++
        return end
    }

    private fun tabAt(start: Int, end: Int = lineEnd(start)): Int {
        var tab = start
        while (tab < end && bytes[tab] != '\t'.code.toByte()) tab++
        return tab
    }

    private fun keyAt(start: Int, tab: Int = tabAt(start)): String =
        normalizeKey(bytes.decodeToString(start, tab).trim())

    private fun valueAt(start: Int): V =
        decodeValue(bytes.decodeToString(tabAt(start) + 1, lineEnd(start)).trim())

    override val entries: Set<Map.Entry<String, V>>
        get() = object : AbstractSet<Map.Entry<String, V>>() {
            override val size: Int get() = this@CompactLexicon.size
            override fun iterator(): Iterator<Map.Entry<String, V>> = sequence {
                for (offset in offsets) if (offset != 0) {
                    val start = offset - 1
                    yield(java.util.AbstractMap.SimpleImmutableEntry(keyAt(start), valueAt(start)))
                }
            }.iterator()
        }

    companion object {
        fun pinyin(file: File): CompactLexicon<String> =
            CompactLexicon(file.readBytes(), { it }, { it }, firstWins = false)

        fun english(file: File): CompactLexicon<List<String>> =
            CompactLexicon(file.readBytes(), { it.substringBefore('(').uppercase() },
                { it.split(Regex("\\s+")).filter(String::isNotEmpty) }, firstWins = true)
    }
}

/** Small corrections overlay the immutable base without copying the entire dictionary. */
internal class OverlayLexicon<V>(
    private val primary: Map<String, V>,
    private val fallback: Map<String, V>,
) : AbstractMap<String, V>() {
    override fun get(key: String): V? = primary[key] ?: fallback[key]
    override fun containsKey(key: String): Boolean = primary.containsKey(key) || fallback.containsKey(key)
    override val entries: Set<Map.Entry<String, V>>
        get() = object : AbstractSet<Map.Entry<String, V>>() {
            override val size: Int get() = primary.size + fallback.keys.count { !primary.containsKey(it) }
            override fun iterator(): Iterator<Map.Entry<String, V>> = sequence {
                yieldAll(primary.entries)
                for (entry in fallback.entries) if (!primary.containsKey(entry.key)) yield(entry)
            }.iterator()
        }
}
