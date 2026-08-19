package com.amphion.dingqiao.demo

import android.app.Application
import android.content.Context
import android.os.Process
import android.os.SystemClock
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.CreateEngineCallback
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.PrepareRuntimeCallback
import com.amphion.dingqiao.SpeechRecognitionEngine
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.police.PoliceEngineConfig
import com.amphion.police.PoliceHotwordProfile
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Cold prepare + prepared-pool create probe for the hotword profile compiled into the APK.
 *
 * This test deliberately does not start recognition and does not sample PSS/RSS. It must be run
 * through [DqCreateOnlyPerfRunner], which replaces the demo [DingqiaoApp] with a plain
 * [Application] and prevents its automatic setLicense/prepareRuntime bootstrap. Performance values
 * are evidence only: assertions below cover identity and lifecycle correctness, never a latency
 * threshold.
 */
@RunWith(AndroidJUnit4::class)
class DqPoliceHotwordCreateOnlyPerformanceInstrumentedTest {
    private val instrumentation
        get() = InstrumentationRegistry.getInstrumentation()
    private val targetContext: Context
        get() = instrumentation.targetContext
    private val testContext: Context
        get() = instrumentation.context

    @Test
    fun measureOneIsolatedPrepareAndCreate() {
        val arguments = InstrumentationRegistry.getArguments()
        val runId = requireArgument(arguments.getString("runId"), "runId")
        require(runId.matches(Regex("[A-Za-z0-9._-]+"))) {
            "runId may contain only letters, digits, dot, underscore and dash"
        }
        val expectedProfile = requireArgument(
            arguments.getString("expectedProfile"),
            "expectedProfile",
        )
        val expectedCount = requireArgument(
            arguments.getString("expectedCount"),
            "expectedCount",
        ).toInt()
        val targetApkSha256 = requireSha256Argument(arguments.getString("targetApkSha256"))
        val testApkSha256 = requireSha256Argument(arguments.getString("testApkSha256"))
        val modelManifestSha256 = requireSha256Argument(
            arguments.getString("modelManifestSha256"),
        )
        val modelPayloadSha256 = requireSha256Argument(
            arguments.getString("modelPayloadSha256"),
        )

        val applicationClass = targetContext.applicationContext.javaClass.name
        assertEquals(
            "create-only runner must suppress DingqiaoApp automatic bootstrap",
            Application::class.java.name,
            applicationClass,
        )

        val profile = PoliceHotwordProfile.defaultProfile()
        assertEquals(expectedProfile, profile.wireValue)
        val hotwords = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = profile,
        )
        assertEquals(expectedCount, hotwords.size)
        assertTrue("compiled profile must contain real hotwords", hotwords.isNotEmpty())
        val effectiveHotwordSha256 = sha256(
            hotwords.joinToString("\n").toByteArray(Charsets.UTF_8),
        )

        var engine: SpeechRecognitionEngine? = null
        var prepareCallCount = 0
        var createCallCount = 0
        try {
            SpeechRecognizeSdk.init(targetContext)
            val perfRoot = File(targetContext.filesDir, PERF_ROOT)
            SpeechRecognizeSdk.setWorkPath(File(perfRoot, "work/$runId").absolutePath)
            activateValidLicense("$PERF_ROOT/license/valid.lic")

            prepareCallCount += 1
            Log.i(TAG, "runId=$runId phase=prepare_start")
            val prepareCpuStartMs = Process.getElapsedCpuTime()
            val prepareStartMs = SystemClock.elapsedRealtime()
            prepareRuntime()
            val prepareMs = SystemClock.elapsedRealtime() - prepareStartMs
            val prepareCpuMs = Process.getElapsedCpuTime() - prepareCpuStartMs
            Log.i(TAG, "runId=$runId phase=prepare_end")

            createCallCount += 1
            Log.i(TAG, "runId=$runId phase=create_start")
            val createCpuStartMs = Process.getElapsedCpuTime()
            val createStartMs = SystemClock.elapsedRealtime()
            engine = createEngine()
            val createMs = SystemClock.elapsedRealtime() - createStartMs
            val createCpuMs = Process.getElapsedCpuTime() - createCpuStartMs
            Log.i(TAG, "runId=$runId phase=create_end")

            val report = linkedMapOf<String, Any?>(
                "schemaVersion" to 1,
                "case" to "police-hotword-create-only",
                "runId" to runId,
                "compiledDefaultProfile" to profile.wireValue,
                "effectiveHotwordCount" to hotwords.size,
                "effectiveHotwordSha256" to effectiveHotwordSha256,
                "applicationClass" to applicationClass,
                "demoBootstrapSuppressed" to true,
                "prepareCallCount" to prepareCallCount,
                "createCallCount" to createCallCount,
                "prepareMs" to prepareMs,
                "prepareCpuMs" to prepareCpuMs,
                "createMs" to createMs,
                "createCpuMs" to createCpuMs,
                "resourceSamplerEnabled" to false,
                "audioRecognitionStarted" to false,
                "targetApkSha256" to targetApkSha256,
                "testApkSha256" to testApkSha256,
                "modelManifestSha256" to modelManifestSha256,
                "modelPayloadSha256" to modelPayloadSha256,
            )
            appendReport(report)
            Log.i(TAG, report.toString())

            assertEquals("test must issue exactly one prepareRuntime call", 1, prepareCallCount)
            assertEquals("test must issue exactly one createEngineAsync call", 1, createCallCount)
        } finally {
            try {
                engine?.shutdown()
            } catch (_: Throwable) {
            }
            try {
                SpeechRecognizeSdk.unloadRuntime()
            } catch (_: Throwable) {
            }
        }
    }

    private fun activateValidLicense(outName: String) {
        val path = stageAsset(
            testContext,
            targetContext,
            "licenses/valid.lic",
            outName,
        )
        val done = CountDownLatch(1)
        var resultCode: Int? = null
        SpeechRecognizeSdk.setLicense(path, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                resultCode = result.errorCode
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                resultCode = errorCode
                done.countDown()
            }
        })
        assertTrue("setLicense callback timed out", done.await(20, TimeUnit.SECONDS))
        assertEquals("valid license must activate", 0, resultCode)
    }

    private fun prepareRuntime() {
        val done = CountDownLatch(1)
        var error: String? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                done.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                error = "$errorCode:$errorMessage"
                done.countDown()
            }
        })
        assertTrue("prepareRuntime callback timed out", done.await(30, TimeUnit.SECONDS))
        assertEquals("prepareRuntime failed", null, error)
    }

    private fun createEngine(): SpeechRecognitionEngine {
        val done = CountDownLatch(1)
        var createdEngine: SpeechRecognitionEngine? = null
        var error: String? = null
        SpeechRecognizeSdk.createEngineAsync(
            CreateEngineParams(language = "zh-CN"),
            object : CreateEngineCallback {
                override fun onSuccess(engine: SpeechRecognitionEngine) {
                    createdEngine = engine
                    done.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    error = "$errorCode:$errorMessage"
                    done.countDown()
                }
            },
        )
        assertTrue("createEngineAsync callback timed out", done.await(120, TimeUnit.SECONDS))
        assertEquals("createEngineAsync failed", null, error)
        return checkNotNull(createdEngine)
    }

    private fun appendReport(fields: Map<String, Any?>) {
        val dir = File(targetContext.filesDir, PERF_ROOT).apply { mkdirs() }
        val obj = JSONObject()
        obj.put("ts", System.currentTimeMillis())
        for ((key, value) in fields) obj.put(key, value ?: JSONObject.NULL)
        File(dir, "report.jsonl").appendText(obj.toString() + "\n", Charsets.UTF_8)
    }

    private fun requireSha256Argument(value: String?): String {
        val normalized = requireArgument(value, "SHA-256 binding")
        require(normalized.matches(Regex("[0-9a-f]{64}"))) {
            "invalid SHA-256 binding"
        }
        return normalized
    }

    private fun requireArgument(value: String?, name: String): String =
        value?.takeIf { it.isNotBlank() } ?: error("missing instrumentation argument: $name")

    companion object {
        private const val TAG = "DqPoliceCreateOnlyPerf"
        private const val PERF_ROOT = "police_hotword_create_only_perf"

        private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
            .digest(bytes)
            .joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }
}
