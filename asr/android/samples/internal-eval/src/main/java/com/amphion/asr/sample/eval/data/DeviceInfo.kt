package com.amphion.asr.sample.eval.data

import android.content.Context
import android.os.Build
import com.amphion.asr.sample.eval.model.DeviceMeta

/**
 * 采集设备硬件 / 系统 / 应用版本信息，落入 [DeviceMeta]。
 *
 * 不采集敏感字段（IMEI / 手机号 / 账号），完全合规：
 * - Build.MODEL / MANUFACTURER：公开品牌信息
 * - Build.VERSION.SDK_INT：Android API level
 * - Build.SUPPORTED_ABIS[0]：当前进程 ABI
 */
object DeviceInfo {

    fun collect(): DeviceMeta = DeviceMeta(
        model = Build.MODEL ?: "unknown",
        manufacturer = Build.MANUFACTURER ?: "unknown",
        androidSdk = Build.VERSION.SDK_INT,
        abi = Build.SUPPORTED_ABIS?.firstOrNull() ?: "unknown",
    )

    /**
     * 取 app 的 versionName；获取失败返回 "0.0.0"，不抛异常。
     * applicationContext 是必需的，避免持有 Activity 引用。
     */
    fun appVersion(ctx: Context): String {
        val pm = ctx.applicationContext.packageManager
        val pkg = ctx.applicationContext.packageName
        return try {
            @Suppress("DEPRECATION")
            pm.getPackageInfo(pkg, 0).versionName ?: "0.0.0"
        } catch (t: Throwable) {
            "0.0.0"
        }
    }

    /** SDK 版本号；0.2.0 起统一通过 [com.amphion.asr.AmphionRuntime.version] 读取。 */
    fun sdkVersion(): String = try {
        com.amphion.asr.AmphionRuntime.version()
    } catch (_: Throwable) {
        "0.0.0"
    }
}
