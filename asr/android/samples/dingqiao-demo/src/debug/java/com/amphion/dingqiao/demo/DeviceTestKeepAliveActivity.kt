package com.amphion.dingqiao.demo

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.TextView

/**
 * Debug-only foreground surface for USB instrumentation on devices that freeze background apps.
 *
 * It intentionally does not touch SpeechRecognizeSdk, so keeping tests visible cannot create,
 * close, or unload a recognizer behind the test's back.
 */
class DeviceTestKeepAliveActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(
            TextView(this).apply {
                gravity = Gravity.CENTER
                text = "ASR device gate running"
                textSize = 20f
            },
        )
    }
}
