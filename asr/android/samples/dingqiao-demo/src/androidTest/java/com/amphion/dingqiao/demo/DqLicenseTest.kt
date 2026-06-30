package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoErrorCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * 离线 License 运行时激活（setLicense）corner-case：到期、设备白名单、包名、能力、损坏、路径。
 * 同时验证“资产 license 已生效但 getLicenseInfo 报 NOT_SET”的接口不一致。
 *
 * 变体 license 用项目签发私钥（与交付 AAR 内置公钥同对）现签，落在 androidTest 资产 licenses/ 下。
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class DqLicenseTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    private data class Activation(val code: Int, val remainingDays: Int?, val features: List<String>?, val errMsg: String?)

    private fun setLicense(assetName: String): Activation {
        val path = stageAsset(testCtx, ctx, "licenses/$assetName", "lic/$assetName")
        return setLicensePath(path)
    }

    private fun setLicensePath(path: String): Activation {
        val latch = CountDownLatch(1)
        var code = -999
        var remaining: Int? = null
        var features: List<String>? = null
        var msg: String? = null
        SpeechRecognizeSdk.setLicense(path, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                code = result.errorCode; remaining = result.remainingDays; features = result.authorizedFeatures; latch.countDown()
            }
            override fun onError(errorCode: Int, errorMessage: String) {
                code = errorCode; msg = errorMessage; latch.countDown()
            }
        })
        latch.await(20, TimeUnit.SECONDS)
        return Activation(code, remaining, features, msg)
    }

    // ---------- L01: 资产 license 已授权但 getLicenseInfo 报 NOT_SET ----------
    @Test
    fun L01_assetLicensed_engineWorks_butInfoNotSet() {
        SpeechRecognizeSdk.init(ctx)
        SpeechRecognizeSdk.setWorkPath(File(ctx.getExternalFilesDir(null), "dq_lic_work").absolutePath)
        // 资产内置 license 使引擎可创建（武装 AAR 必须通过授权才会成功）。
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE),
        )
        var infoThrew: Int? = null
        try {
            SpeechRecognizeSdk.getLicenseInfo()
        } catch (t: Throwable) {
            infoThrew = runCatching { t.javaClass.getMethod("getErrorCode").invoke(t) as? Int }.getOrNull()
        }
        engine.shutdown()
        DqReport.append(ctx, mapOf("case" to "L01_infoNotSetWhileLicensed", "getLicenseInfoErrorCode" to infoThrew))
        assertEquals("engine licensed via asset, yet getLicenseInfo throws NOT_SET",
            DingqiaoErrorCode.LICENSE_NOT_SET, infoThrew)
    }

    // ---------- L10: 合法 demo license ----------
    @Test
    fun L10_setValid_ok() {
        val a = setLicense("valid.lic")
        val info = runCatching { SpeechRecognizeSdk.getLicenseInfo() }.getOrNull()
        DqReport.append(ctx, mapOf("case" to "L10_valid", "code" to a.code, "remainingDays" to a.remainingDays,
            "features" to a.features?.toString(), "infoStatus" to info?.status, "infoFeatures" to info?.authorizedFeatures?.toString()))
        assertEquals("valid license should activate", 0, a.code)
        assertTrue("features should contain ASR", a.features?.contains("ASR") == true)
    }

    // ---------- L20: 过期 ----------
    @Test
    fun L20_setExpired() {
        val a = setLicense("expired.lic")
        DqReport.append(ctx, mapOf("case" to "L20_expired", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_EXPIRED, a.code)
    }

    // ---------- L30: 设备白名单不含本机 ----------
    @Test
    fun L30_setDeviceMismatch() {
        val a = setLicense("device_mismatch.lic")
        DqReport.append(ctx, mapOf("case" to "L30_deviceMismatch", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH, a.code)
    }

    // ---------- L40: SN 白名单含本机；非特权 demo app 读不到 SN -> DEVICE_MISMATCH ----------
    @Test
    fun L40_setDeviceMatch_mySn() {
        val a = setLicense("device_match.lic")
        DqReport.append(ctx, mapOf("case" to "L40_deviceMatch_mySn", "code" to a.code, "msg" to a.errMsg,
            "note" to "license bound to real SN; demo app lacks READ_PRIVILEGED_PHONE_STATE so SN unreadable -> DEVICE_MISMATCH. Only the privileged host com.tdtech.tiassistant can pass SN-bound license."))
        // 本机在白名单内，但 demo app 无特权读不到 SN -> 设备校验失败。这是 Android 权限约束，非 SDK 缺陷。
        assertEquals(DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH, a.code)
    }

    // ---------- L41: 记录 demo app 实际可见的设备 SN（佐证 L40 根因） ----------
    @Test
    fun L41_deviceSerialVisibility() {
        val getSerial = runCatching {
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) android.os.Build.getSerial()
            else @Suppress("DEPRECATION") android.os.Build.SERIAL
        }
        val sysProp = runCatching {
            val clazz = Class.forName("android.os.SystemProperties")
            val get = clazz.getMethod("get", String::class.java)
            get.invoke(null, "ro.serialno") as? String
        }.getOrNull()
        val getprop = runCatching {
            val p = ProcessBuilder("getprop", "ro.serialno").redirectErrorStream(true).start()
            p.inputStream.bufferedReader().use { it.readText() }.trim()
        }.getOrNull()
        DqReport.append(ctx, mapOf(
            "case" to "L41_serialVisibility",
            "build_getSerial" to (getSerial.getOrNull() ?: "EXC:${getSerial.exceptionOrNull()?.javaClass?.simpleName}"),
            "systemProperties_ro_serialno" to (sysProp ?: ""),
            "getprop_ro_serialno" to (getprop ?: ""),
        ))
    }

    // ---------- L50: 包名不匹配（注意会被归并成 DEVICE_MISMATCH 码） ----------
    @Test
    fun L50_setAppMismatch() {
        val a = setLicense("app_mismatch.lic")
        DqReport.append(ctx, mapOf("case" to "L50_appMismatch", "code" to a.code, "msg" to a.errMsg,
            "note" to "app/cert/device mismatch all surface as LICENSE_DEVICE_MISMATCH(1002200033)"))
        assertEquals(DingqiaoErrorCode.LICENSE_DEVICE_MISMATCH, a.code)
    }

    // ---------- L60: 仅 TTS 能力，缺 ASR ----------
    @Test
    fun L60_setTtsOnly_featureMissing() {
        val a = setLicense("tts_only.lic")
        DqReport.append(ctx, mapOf("case" to "L60_ttsOnly", "code" to a.code, "msg" to a.errMsg,
            "note" to "feature-missing maps to LICENSE_ACTIVATION_FAILED(1002200035)"))
        assertEquals(DingqiaoErrorCode.LICENSE_ACTIVATION_FAILED, a.code)
    }

    // ---------- L70: ASR,TTS 共用 license ----------
    @Test
    fun L70_setAsrTts_ok() {
        val a = setLicense("asr_tts.lic")
        DqReport.append(ctx, mapOf("case" to "L70_asrTts", "code" to a.code, "features" to a.features?.toString()))
        assertEquals(0, a.code)
        assertTrue("ASR present", a.features?.contains("ASR") == true)
        assertTrue("TTS present", a.features?.contains("TTS") == true)
    }

    // ---------- L80: 损坏信封 ----------
    @Test
    fun L80_setMalformed() {
        val a = setLicense("malformed.lic")
        DqReport.append(ctx, mapOf("case" to "L80_malformed", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_INVALID, a.code)
    }

    // ---------- L85: 路径不存在 ----------
    @Test
    fun L85_setMissingPath() {
        val a = setLicensePath(File(ctx.filesDir, "no_such.lic").absolutePath)
        DqReport.append(ctx, mapOf("case" to "L85_missingPath", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, a.code)
    }

    // ---------- L90: 恢复合法 license，便于后续类复用 ----------
    @Test
    fun L90_restoreValid() {
        val a = setLicense("valid.lic")
        DqReport.append(ctx, mapOf("case" to "L90_restoreValid", "code" to a.code))
        assertEquals(0, a.code)
    }
}
