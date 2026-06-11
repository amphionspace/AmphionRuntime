package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionRuntime
import com.amphion.asr.SpeakerEnroller
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * 鼎桥语音识别 SDK 入口，对齐 [语音识别SDK接口.md]。
 *
 * Android 平台须先调用 [init] 注入 [Context]，再 [setWorkPath]。
 */
object SpeechRecognizeSdk {

    @Volatile
    private var appContext: Context? = null

    @Volatile
    private var workPath: File? = null

    private val engineExecutor: ExecutorService = Executors.newCachedThreadPool { r ->
        Thread(r, "dingqiao-engine").apply { isDaemon = true }
    }

    /**
     * Android 平台初始化（须在 [createEngine] / [registerVoiceprint] 之前调用一次）。
     */
    @JvmStatic
    fun init(context: Context) {
        val ctx = context.applicationContext ?: context
        if (appContext == null) {
            synchronized(this) {
                if (appContext == null) {
                    appContext = ctx
                    AmphionRuntime.init(ctx)
                }
            }
        }
    }

    /**
     * 指定 SDK 工作目录（声纹、speaker 模型等）。须在 [createEngine] 之前调用。
     */
    @JvmStatic
    fun setWorkPath(path: String) {
        val dir = File(path)
        dir.mkdirs()
        require(dir.isDirectory && dir.canWrite()) { "workPath must be writable: $path" }
        workPath = dir
    }

    /**
     * 创建识别引擎（同步）。
     */
    @JvmStatic
    fun createEngine(params: CreateEngineParams): SpeechRecognitionEngine {
        val ctx = requireContext()
        val store = requireStore()
        val speakerModel = store.speakerModelPath().takeIf { it.isFile }?.absolutePath
        return DingqiaoRecognitionEngine.create(
            appContext = ctx,
            params = params,
            voiceprintStore = store,
            speakerModelPath = speakerModel,
        )
    }

    /**
     * 创建识别引擎（异步回调）。
     */
    @JvmStatic
    fun createEngine(params: CreateEngineParams, callback: CreateEngineCallback) {
        engineExecutor.execute {
            try {
                val engine = createEngine(params)
                callback.onResult(engine)
            } catch (t: Throwable) {
                val code = (t as? DingqiaoEngineException)?.errorCode
                    ?: DingqiaoErrorCode.CREATE_ENGINE_FAILED
                callback.onError(code, t.message ?: "createEngine failed")
            }
        }
    }

    /**
     * 注册声纹：3~5 条样本，每条 3~8 秒。
     */
    @JvmStatic
    fun registerVoiceprint(params: VoiceprintRegisterParams): VoiceprintRegisterResult {
        params.audioInfo.validate()
        val count = params.samplePaths.size
        if (count !in DINGQIAO_VOICEPRINT_MIN_SAMPLES..DINGQIAO_VOICEPRINT_MAX_SAMPLES) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_SAMPLE_COUNT,
                "sample count must be $DINGQIAO_VOICEPRINT_MIN_SAMPLES..$DINGQIAO_VOICEPRINT_MAX_SAMPLES",
            )
        }
        val store = requireStore()
        val modelPath = store.speakerModelPath()
        if (!modelPath.isFile) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED,
                "speaker model not found: ${modelPath.absolutePath}",
            )
        }
        val segments = mutableListOf<FloatArray>()
        val minMs = DINGQIAO_VOICEPRINT_MIN_SEC * 1000L
        val maxMs = DINGQIAO_VOICEPRINT_MAX_SEC * 1000L
        for (path in params.samplePaths) {
            val file = File(path)
            if (!file.isFile) {
                throw DingqiaoEngineException(
                    DingqiaoErrorCode.VOICEPRINT_REGISTER_FAILED,
                    "sample not found: $path",
                )
            }
            val pcm = PcmIo.readPcm16k(file)
            val durationMs = PcmIo.durationMs(pcm.size)
            if (durationMs !in minMs..maxMs) {
                throw DingqiaoEngineException(
                    DingqiaoErrorCode.VOICEPRINT_SAMPLE_DURATION,
                    "sample duration must be ${DINGQIAO_VOICEPRINT_MIN_SEC}s..${DINGQIAO_VOICEPRINT_MAX_SEC}s: $path",
                )
            }
            segments += PcmIo.shortsToFloats(pcm)
        }
        return SpeakerEnroller(modelPath.absolutePath).use { enroller ->
            val embedding = enroller.enroll(segments)
            store.saveVoiceprint(params.samplePaths, embedding)
        }
    }

    /**
     * 删除声纹。
     */
    @JvmStatic
    fun deleteVoiceprint(voiceprintId: String) {
        val store = requireStore()
        if (!store.deleteVoiceprint(voiceprintId)) {
            throw DingqiaoEngineException(
                DingqiaoErrorCode.VOICEPRINT_NOT_FOUND,
                "voiceprint not found: $voiceprintId",
            )
        }
    }

    private fun requireContext(): Context =
        appContext ?: throw IllegalStateException("SpeechRecognizeSdk.init(context) must be called first")

    private fun requireStore(): VoiceprintStore {
        val path = workPath ?: throw IllegalStateException("SpeechRecognizeSdk.setWorkPath() must be called first")
        return VoiceprintStore(path)
    }
}
