package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.StartParams
import java.io.File
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Requires the hashed V6 acceptance fixtures documented in the PR #218 evidence. */
@RunWith(AndroidJUnit4::class)
class DingqiaoVadPendingSpeechInstrumentedTest {
    @Test fun vadEndpointPreservesPendingWordTails() {
        val ctx = InstrumentationRegistry.getInstrumentation().targetContext
        val tc = InstrumentationRegistry.getInstrumentation().context
        prepareSdkRuntime(ctx, File(ctx.getExternalFilesDir(null), "pending_vad_test"))
        val engine = SpeechRecognizeSdk.createEngine(CreateEngineParams(
            language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE,
        ))
        val failures = mutableListOf<String>()
        try {
            for ((asset, expected) in listOf(
                "v6_1_1.wav" to "开启记录仪NFC", "v6_1_2.wav" to "开启记录仪NFC",
                "v6_2_1.wav" to "把录像分辨率设置为D幺", "v6_2_2.wav" to "把录像分辨率设置为D幺",
                "v6_6_2.wav" to "把记录仪亮度调到零档",
            )) {
                val sid = "pending-vad-${asset.substringBefore('.')}"
                val listener = CapturingListener()
                engine.setListener(listener)
                engine.startListening(StartParams(sid, AudioInfo(), mapOf(
                    "vadEnd" to 800, "enablePoliceEnhancement" to true,
                    "enablePartialResult" to true, "maxAudioDuration" to 60_000,
                )))
                assertTrue(listener.awaitStarted(15_000))
                feedFrames(engine, sid, readAssetPcm(tc, asset), DQ_FRAME_MS)
                feedFrames(engine, sid, ByteArray(DQ_SR * 2 * 2), DQ_FRAME_MS)
                DqReport.append(ctx, mapOf("case" to "pending_vad_before_finish", "sessionId" to sid,
                    "file" to asset, "lasts" to listener.finals.count { it.isLast },
                    "finalText" to listener.finalText()))
                assertEquals(0, listener.finals.count { it.isLast })
                assertTrue(listener.completes.isEmpty())
                engine.finish(sid)
                assertTrue(listener.awaitComplete(20_000))
                val text = listener.finalText().replace(Regex("[\\s\\p{P}]+"), "")
                val textPassed = text == expected
                DqReport.append(ctx, mapOf("case" to "pending_vad_result", "sessionId" to sid,
                    "file" to asset, "text" to listener.finalText(), "expected" to expected,
                    "textPassed" to textPassed, "lasts" to listener.finals.count { it.isLast },
                    "completes" to listener.completes.size, "errors" to listener.errors.toString()))
                if (!textPassed) failures.add("$asset: $text, expected $expected")
                assertEquals(1, listener.finals.count { it.isLast })
                assertEquals(1, listener.completes.size)
                assertTrue(listener.errors.isEmpty())
                val terminal = listener.callbackTrace.filter { it.isLast || it.kind == CapturedCallbackKind.COMPLETE }
                assertEquals(listOf(CapturedCallbackKind.FINAL, CapturedCallbackKind.COMPLETE), terminal.map { it.kind })
                assertTrue(listener.callbackTrace.all { it.sessionId == sid })
            }
        } finally { engine.shutdown() }
        assertTrue(failures.joinToString("\n"), failures.isEmpty())
    }
}
