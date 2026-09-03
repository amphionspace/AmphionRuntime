package com.lits.tts.aarhost

import android.app.Activity
import android.os.Bundle
import android.view.WindowManager
import android.widget.TextView

/** Keeps the instrumented host foreground on devices that freeze background test processes. */
class AarHostActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(TextView(this).apply { text = "Release AAR 公共接口验收中，请保持此页面在前台。" })
    }
}
