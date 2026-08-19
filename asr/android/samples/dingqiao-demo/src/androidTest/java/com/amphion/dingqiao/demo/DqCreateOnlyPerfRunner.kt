package com.amphion.dingqiao.demo

import android.app.Application
import android.content.Context
import androidx.test.runner.AndroidJUnitRunner

/**
 * Runs the create-only probe with a plain [Application].
 *
 * The delivery demo's [DingqiaoApp] intentionally bootstraps the license and runtime from
 * `Application.onCreate()`. That is correct for the interactive demo, but would preload the model
 * before a cold prepare/create measurement. This runner is a separate manifest component used only
 * by the create-only host runner, so existing instrumentation keeps the normal demo application.
 */
class DqCreateOnlyPerfRunner : AndroidJUnitRunner() {
    override fun newApplication(
        cl: ClassLoader,
        className: String,
        context: Context,
    ): Application = super.newApplication(cl, Application::class.java.name, context)
}
