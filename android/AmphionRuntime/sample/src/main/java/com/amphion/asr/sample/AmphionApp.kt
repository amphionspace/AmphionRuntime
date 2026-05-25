package com.amphion.asr.sample

import android.app.Application
import android.util.Log

/**
 * Application 入口：在任何 Activity 启动前异步触发 [ModelImporter]，
 * 把 externalFilesDir/asr-models-import 的待导入模型搬到 internal storage。
 *
 * 为什么放在 Application 而非各 Activity 的 onCreate：
 * - MainActivity 和 LandingActivity 是两个独立的入口路径，都需要 import
 * - 在 Application 触发 = 单一入口，避免重复或漏触发
 * - Application onCreate 必然在所有 Activity onCreate 之前执行
 *
 * 异步执行原因：copyRecursively 300+ MB 模型在手机 NAND 上要 10-30s，
 * 主线程跑会 ANR；worker thread 让 UI 立即响应，第一次进录音页时引擎卡片
 * 会短暂显示「加载中」，import 完成后自动 readout。
 */
class AmphionApp : Application() {

    override fun onCreate() {
        super.onCreate()
        Thread({
            try {
                val imported = ModelImporter(applicationContext).importIfPresent()
                if (imported.isNotEmpty()) {
                    Log.i(TAG, "imported ${imported.size} model version(s) at app startup")
                }
            } catch (t: Throwable) {
                Log.w(TAG, "model import at startup failed: ${t.message}")
            }
        }, "amphion-app-import").apply { isDaemon = true; start() }
    }

    companion object {
        private const val TAG = "AmphionApp"
    }
}
