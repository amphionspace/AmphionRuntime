package com.lits.tts.sdk.internal

import android.content.Context

internal object AndroidAppContext {
    fun tryGet(): Context? {
        currentApplication()?.let { return it.applicationContext }
        initialApplication()?.let { return it.applicationContext }
        return null
    }

    @Suppress("UNCHECKED_CAST")
    private fun currentApplication(): Context? = runCatching {
        val klass = Class.forName("android.app.ActivityThread")
        val method = klass.getMethod("currentApplication")
        method.invoke(null) as? Context
    }.getOrNull()

    @Suppress("UNCHECKED_CAST")
    private fun initialApplication(): Context? = runCatching {
        val klass = Class.forName("android.app.AppGlobals")
        val method = klass.getMethod("getInitialApplication")
        method.invoke(null) as? Context
    }.getOrNull()
}
