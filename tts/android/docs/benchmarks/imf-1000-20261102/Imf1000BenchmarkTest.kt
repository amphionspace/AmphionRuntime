package com.lits.tts.aarhost

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import com.lits.tts.sdk.*
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test

class Imf1000BenchmarkTest {
    private fun rss(): Long = File("/proc/self/status").readLines().first { it.startsWith("VmRSS:") }.trim().split(Regex("\\s+"))[1].toLong()
    private fun now() = SystemClock.elapsedRealtimeNanos()
    @Test fun benchmark() {
        val c = ApplicationProvider.getApplicationContext<Context>()
        check(c.packageName == "com.lits.tts.demo31")
        val out = File(c.filesDir, "benchmark1000-20261102")
        check(!out.exists()) { "Refusing to overwrite an earlier run" }
        check(out.mkdirs())
        val summary = JSONObject()
        val phases = JSONArray()
        val epoch = now()
        fun phase(name:String) {
            val item=JSONObject().put("phase",name).put("elapsedMs",(now()-epoch)/1e6).put("rssKiB",rss())
            phases.put(item)
            File(out,"phases.json").writeText(phases.toString(2))
        }
        fun conditions(): JSONObject {
            val battery=c.registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            return JSONObject().put("batteryTemperatureC",(battery?.getIntExtra("temperature",-1)?:-1)/10.0)
                .put("thermalStatus",(c.getSystemService(Context.POWER_SERVICE) as PowerManager).currentThermalStatus)
        }
        val active=AtomicInteger(-3)
        val running=AtomicBoolean(true)
        val samples=File(out,"memory.csv").bufferedWriter()
        samples.write("elapsed_ms,request_index,rss_kib\n")
        val sampler=Thread {
            var count=0
            try {
                while(running.get()) {
                    samples.write("${(now()-epoch)/1e6},${active.get()},${rss()}\n")
                    if(++count%100==0) samples.flush()
                    Thread.sleep(20)
                }
            } finally {samples.close()}
        }
        val rows=File(out,"rows.jsonl").bufferedWriter()
        var engine:TextToSpeechEngine?=null
        var completed=0
        phase("before_sdk_init")
        summary.put("conditionsBefore",conditions())
        sampler.start()
        try {
            val license=File(c.filesDir,"tts-provisioning/amphion-license.lic").readText()
            val sn=File(c.filesDir,"tts-provisioning/device-sn.txt").readText().trim()
            val initStart=now()
            TextToSpeechSdk.setWorkPath(File(c.filesDir,"lits-tts-work").absolutePath)
            TextToSpeechSdk.init(c,TtsLicenseOptions(license=license,licenseAssetName=null,deviceIdProvider=TtsDeviceIdProvider {sn}))
            summary.put("initMs",(now()-initStart)/1e6)
            phase("after_sdk_init")
            active.set(-2)
            val loadStart=now()
            val e=TextToSpeechSdk.createEngine(CreateEngineParams("zh-en",RunMode.OFFLINE,"lits-female-02"))
            engine=e
            summary.put("createEngineMs",(now()-loadStart)/1e6)
            phase("after_model_load")
            val texts=listOf(
                "你好，欢迎使用语音合成。",
                "今天阳光明媚，我们沿着河边慢慢散步。",
                "当前经度是104.068299，纬度是30.541967。",
                "圆周率精确到小数点后八位是3.14159265。",
                "请在下午三点参加会议，会议室位于二楼。",
                "Hello, welcome to our speech synthesis demonstration.",
                "The future depends on what we do today, and every small step matters.",
                "今天我们讨论 artificial intelligence，以及它对日常生活的影响。",
                "房间已经准备好了，room two hundred and four is ready. 请随我来。",
                "人们常常在匆忙中寻找生活的答案，却忘记观察眼前的世界。清晨的光线落在窗边，街道逐渐苏醒。我们愿意花一点时间倾听，也愿意在不确定之中保持耐心，因为真正的理解，需要思考，也需要实践。"
            )

            File(out,"inputs.json").writeText(JSONArray(texts).toString(2))
            for(i in -1 until 1000) {
                val text=if(i<0) texts[0] else texts[i%texts.size]
                val requestId="bench1000-$i"
                val done=CountDownLatch(1)
                var firstNs=0L
                var lastNs=0L
                var completedNs=0L
                var gapNs=0L
                var bytes=0L
                var chunks=0
                var error:String?=null
                var started:StartResponse?=null
                var complete:CompleteResponse?=null
                e.setListener(object:SpeakListener {
                    override fun onStart(id:String,response:StartResponse) {started=response}
                    override fun onData(id:String,audio:ByteArray,response:SynthesisResponse) {
                        val received=now()
                        if(id!=requestId) error="request ID mismatch: $id"
                        if(response.sequence!=chunks) error="sequence mismatch: ${response.sequence} != $chunks"
                        if(audio.isNotEmpty()) {
                            if(firstNs==0L) firstNs=received
                            if(lastNs>0L) gapNs=maxOf(gapNs,received-lastNs)
                            lastNs=received
                        }
                        bytes+=audio.size; chunks++
                    }
                    override fun onComplete(id:String,response:CompleteResponse) {
                        if(response.type==CompleteType.SYNTHESIS_COMPLETE) {completedNs=now();complete=response;done.countDown()}
                    }
                    override fun onError(id:String,errorCode:Int,errorMessage:String) {error="$errorCode:$errorMessage";done.countDown()}
                })
                val beforeRss=rss()
                active.set(i)
                val submitted=now()
                e.speak(text,SpeakParams(requestId=requestId,playType=PlayType.SYNTHESIZE_ONLY,languageContext="zh-en",streamingConfig=TtsStreamingConfig(chunkSize=50)))
                val finished=done.await(90,TimeUnit.SECONDS)
                val end=now()
                val afterRss=rss()
                active.set(-4)
                val start=started
                val audioMs=if(start!=null) bytes*1000.0/(start.sampleRate*start.audioChannel*(start.sampleBit/8)) else 0.0
                val completionMs=if(completedNs>0)(completedNs-submitted)/1e6 else -1.0
                val row=JSONObject().put("index",i).put("inputId",if(i<0) 0 else i%texts.size).put("textChars",text.length)
                    .put("submittedElapsedMs",(submitted-epoch)/1e6).put("endedElapsedMs",(end-epoch)/1e6)
                    .put("firstPacketMs",if(firstNs>0)(firstNs-submitted)/1e6 else JSONObject.NULL)
                    .put("lastPacketMs",if(lastNs>0)(lastNs-submitted)/1e6 else JSONObject.NULL)
                    .put("completionMs",completionMs).put("completionAfterLastPacketMs",if(lastNs>0 && completedNs>0)(completedNs-lastNs)/1e6 else JSONObject.NULL)
                    .put("maxInterPacketGapMs",gapNs/1e6).put("audioDurationMs",audioMs)
                    .put("rtf",if(audioMs>0 && completionMs>=0) completionMs/audioMs else JSONObject.NULL)
                    .put("pcmBytes",bytes).put("chunks",chunks).put("beforeRssKiB",beforeRss).put("afterRssKiB",afterRss)
                    .put("error",error?:JSONObject.NULL).put("finished",finished)
                    .put("sdkFirstPacketMs",complete?.firstPacketMs).put("sdkSynthesisMs",complete?.synthesisMs)
                if(i<0 || i%100==99) row.put("conditions",conditions())
                rows.write(row.toString()+"\n");rows.flush()
                if(i<0) {
                    summary.put("modelInfo",start?.modelInfo).put("loadProfileInfo",start?.loadProfileInfo)
                        .put("coldInitToFirstPacketMs",(firstNs-initStart)/1e6)
                        .put("sampleRate",start?.sampleRate).put("sampleBit",start?.sampleBit).put("audioChannel",start?.audioChannel)
                        .put("chunkSize",start?.streamingChunkSize).put("pcmQueueCapacity",start?.pcmQueueCapacity)
                    phase("after_cold_synthesis")
                    File(out,"summary.json").writeText(summary.toString(2))
                } else completed++
                if(i<0 || i%10==9) Log.i("Imf1000Benchmark","completed=$completed firstMs=${row.opt("firstPacketMs")} lastMs=${row.opt("lastPacketMs")} rssKiB=$afterRss")
                check(finished && error==null && bytes>0 && start?.streamingChunkSize==50) {"failed round $i: $row"}
            }
            phase("after_1000_synthesis")
        } finally {
            summary.put("completedWarmRequests",completed).put("conditionsAfter",conditions())
            phase("before_engine_shutdown")
            val releaseStart=now()
            engine?.shutdown()
            summary.put("shutdownMs",(now()-releaseStart)/1e6)
            phase("after_engine_shutdown")
            Thread.sleep(2000)
            phase("two_seconds_after_shutdown")
            summary.put("totalElapsedMs",(now()-epoch)/1e6)
            File(out,"summary.json").writeText(summary.toString(2))
            running.set(false);sampler.join();rows.close()
        }
    }
}
