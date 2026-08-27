package com.amphion.police.person

internal data class PersonEntitySpan(val start: Int, val end: Int)

internal class LacPersonNer(
    modelPath: String,
    transitionsPath: String,
    wordPath: String,
    tagPath: String,
    q2bPath: String,
) : AutoCloseable {
    private var handle = nativeCreate(modelPath, transitionsPath, wordPath, tagPath, q2bPath)

    init { check(handle != 0L) { "LAC person NER model load failed" } }

    @Synchronized
    fun findPersonSpans(text: String): List<PersonEntitySpan> {
        check(handle != 0L) { "LAC person NER is closed" }
        val flattened = nativeFindPersonSpans(handle, text)
        check(flattened.size % 2 == 0) { "invalid LAC person span output" }
        return List(flattened.size / 2) { index ->
            PersonEntitySpan(flattened[index * 2], flattened[index * 2 + 1])
        }
    }

    @Synchronized
    override fun close() {
        if (handle == 0L) return
        nativeClose(handle)
        handle = 0L
    }

    private external fun nativeCreate(
        modelPath: String,
        transitionsPath: String,
        wordPath: String,
        tagPath: String,
        q2bPath: String,
    ): Long
    private external fun nativeFindPersonSpans(handle: Long, text: String): IntArray
    private external fun nativeClose(handle: Long)

    private companion object {
        init { System.loadLibrary("amphion_police_jni") }
    }
}
