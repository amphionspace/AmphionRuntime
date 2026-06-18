package com.amphion.dingqiao.demo

import android.app.Application
import android.util.Log
import com.amphion.dingqiao.DINGQIAO_SPEAKER_MODEL_FILENAME
import com.amphion.dingqiao.SpeechRecognizeSdk
import java.io.File

/**
 * 鼎桥交付 Demo 入口：初始化 [SpeechRecognizeSdk] 与工作目录。
 */
class DingqiaoApp : Application() {

    lateinit var workDir: File
        private set

    override fun onCreate() {
        super.onCreate()
        instance = this
        workDir = File(getExternalFilesDir(null), "dingqiao_work").apply { mkdirs() }
        SpeechRecognizeSdk.init(this)
        SpeechRecognizeSdk.setWorkPath(workDir.absolutePath)

        val speakerModel = File(workDir, DINGQIAO_SPEAKER_MODEL_FILENAME)
        if (!speakerModel.isFile) {
            Log.w(TAG, "speaker model missing: ${speakerModel.absolutePath}")
        }
    }

    companion object {
        private const val TAG = "DingqiaoDemo"

        @Volatile
        private lateinit var instance: DingqiaoApp

        fun workPath(): String = instance.workDir.absolutePath
    }
}
