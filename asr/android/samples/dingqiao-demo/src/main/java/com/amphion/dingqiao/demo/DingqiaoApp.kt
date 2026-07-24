package com.amphion.dingqiao.demo

import android.app.Application
import android.util.Log
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.SpeechRecognizeSdk
import java.io.File

/**
 * 鼎桥交付 Demo 入口：初始化 [SpeechRecognizeSdk] 与工作目录。
 */
class DingqiaoApp : Application() {

    lateinit var workDir: File
        private set

    private val runtimeLock = Any()
    private val runtimeCallbacks = mutableListOf<(RuntimeInitResult) -> Unit>()
    private var runtimeResult: RuntimeInitResult? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        workDir = File(getExternalFilesDir(null), "dingqiao_work").apply { mkdirs() }
        SpeechRecognizeSdk.init(this)
        SpeechRecognizeSdk.setWorkPath(workDir.absolutePath)
        prepareRuntime()

        val speakerModel = VoiceprintModelHelper.modelFile(workDir.absolutePath)
        if (!VoiceprintModelHelper.isReady(speakerModel)) {
            Log.w(TAG, "speaker model not ready: exists=${speakerModel.exists()} " +
                "canRead=${speakerModel.canRead()} size=${speakerModel.length()} " +
                "path=${speakerModel.absolutePath}")
        }
    }

    fun whenRuntimeReady(callback: (RuntimeInitResult) -> Unit) {
        val completed = synchronized(runtimeLock) {
            runtimeResult ?: run {
                runtimeCallbacks += callback
                null
            }
        }
        if (completed != null) callback(completed)
    }

    private fun prepareRuntime() {
        val licenseFile = File(filesDir, LICENSE_ASSET)
        try {
            assets.open(LICENSE_ASSET).use { input ->
                licenseFile.outputStream().use { output -> input.copyTo(output) }
            }
        } catch (t: Throwable) {
            completeRuntime(
                RuntimeInitResult(
                    errorCode = LOCAL_LICENSE_COPY_ERROR,
                    errorMessage = t.message ?: "failed to copy $LICENSE_ASSET",
                ),
            )
            return
        }

        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) {
                    SpeechRecognizeSdk.prepareRuntime(
                        object : PrepareRuntimeCallback {
                            override fun onReady() {
                                completeRuntime(RuntimeInitResult())
                            }

                            override fun onError(errorCode: Int, errorMessage: String) {
                                completeRuntime(RuntimeInitResult(errorCode, errorMessage))
                            }
                        },
                    )
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    completeRuntime(RuntimeInitResult(errorCode, errorMessage))
                }
            },
        )
    }

    private fun completeRuntime(result: RuntimeInitResult) {
        val callbacks = synchronized(runtimeLock) {
            if (runtimeResult != null) return
            runtimeResult = result
            runtimeCallbacks.toList().also { runtimeCallbacks.clear() }
        }
        callbacks.forEach { it(result) }
    }

    data class RuntimeInitResult(
        val errorCode: Int = 0,
        val errorMessage: String = "",
    ) {
        val isReady: Boolean get() = errorCode == 0
    }

    companion object {
        private const val TAG = "DingqiaoDemo"
        private const val LICENSE_ASSET = "amphion-license.lic"
        private const val LOCAL_LICENSE_COPY_ERROR = -1

        @Volatile
        private lateinit var instance: DingqiaoApp

        fun workPath(): String = instance.workDir.absolutePath
    }
}
