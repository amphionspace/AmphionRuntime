package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionLicenseStatus
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
    }

    override fun isRuntimeReady(): Boolean = AmphionRuntime.isRuntimeReady()

    override fun unloadModel() {
        AmphionRuntime.unloadModel()
    }

    override fun unloadRuntime() {
        AmphionRuntime.release()
    }
}
