package com.amphion.asr.sample.eval.data

import android.content.Context
import android.util.Log
import com.amphion.asr.sample.eval.model.SentenceManifest
import java.io.File

/**
 * 测试集仓库。
 *
 * 加载优先级：
 * 1. `<externalFilesDir>/asr-eval-set/sentences.json`（adb push 覆盖外部版本）
 * 2. `assets/eval-set/sentences.json`（APK 内置 fallback）
 *
 * 外部版本解析失败时自动回退到内置版本，并 log warn 让工程师定位。
 *
 * 整个 manifest 一次性加载到内存（< 50KB），不做懒加载；多个 Activity 共用一个 [SentenceRepository]
 * 实例（由 EvalActivity 持有，跨页面通过 Intent 传 sentence_id）。
 */
class SentenceRepository private constructor(val manifest: SentenceManifest, val source: Source) {

    enum class Source { EXTERNAL, ASSETS }

    companion object {
        private const val TAG = "SentenceRepository"
        private const val EXTERNAL_DIR = "asr-eval-set"
        private const val FILE_NAME = "sentences.json"
        private const val ASSETS_PATH = "eval-set/sentences.json"

        /**
         * 加载测试集。永远返回一个可用 manifest（外部失败时自动 fallback 内置），
         * 调用方只需要 try 一次外部异常然后 fallback 即可的逻辑都封到这里。
         *
         * @throws IllegalStateException 仅当内置 assets 也加载失败时（基本不会发生）
         */
        fun load(ctx: Context): SentenceRepository {
            val external = externalFile(ctx)
            if (external.isFile) {
                try {
                    val text = external.readText(Charsets.UTF_8)
                    val m = SentenceManifest.fromJson(text)
                    Log.i(TAG, "loaded ${m.sentenceCount} sentences from EXTERNAL ${external.absolutePath}")
                    return SentenceRepository(m, Source.EXTERNAL)
                } catch (t: Throwable) {
                    Log.w(TAG, "external manifest invalid (${t.message}), falling back to assets")
                }
            }

            val text = ctx.assets.open(ASSETS_PATH).bufferedReader(Charsets.UTF_8).use { it.readText() }
            val m = SentenceManifest.fromJson(text)
            Log.i(TAG, "loaded ${m.sentenceCount} sentences from ASSETS $ASSETS_PATH")
            return SentenceRepository(m, Source.ASSETS)
        }

        fun externalFile(ctx: Context): File {
            val base = ctx.getExternalFilesDir(null) ?: ctx.filesDir
            return File(File(base, EXTERNAL_DIR), FILE_NAME)
        }
    }
}
