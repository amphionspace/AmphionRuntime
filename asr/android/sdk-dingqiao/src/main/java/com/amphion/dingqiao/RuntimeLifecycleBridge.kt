package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AsrLanguage
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AmphionRuntime

internal interface RuntimeLifecycleBridge {
    fun validateLicense(context: Context, options: AmphionOptions): AmphionLicenseStatus
    fun prepareRuntime(context: Context, options: AmphionOptions)
    fun isRuntimeReady(): Boolean
    fun unloadModel()
    fun unloadRuntime()
}

internal object AndroidRuntimeLifecycleBridge : RuntimeLifecycleBridge {
    override fun validateLicense(
        context: Context,
        options: AmphionOptions,
    ): AmphionLicenseStatus = AmphionRuntime.validateLicense(context, options)

    override fun prepareRuntime(context: Context, options: AmphionOptions) {
        AmphionRuntime.init(context, options)
        // prepareRuntime 是 SDK 对外的“后续 createEngine 可快速返回”承诺。这里用鼎桥默认
        // ZH_EN recognizer 配置完成一次真实构建并归还进程池；VAD 仍是 engine 级轻量资源，
        // createEngine 时重新构造，不让预热实例泄漏到业务生命周期。
        val config = DingqiaoEngineConfig.buildAsrConfig(
            CreateEngineParams(language = "zh-CN"),
            speakerModelPath = null,
        )
        AmphionRuntime.create(context, AsrLanguage.ZH_EN, config).close()
    }

    override fun isRuntimeReady(): Boolean = AmphionRuntime.isRuntimeReady()

    override fun unloadModel() {
        AmphionRuntime.unloadModel()
    }

    override fun unloadRuntime() {
        AmphionRuntime.release()
    }
}
