package com.amphion.dingqiao.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DingqiaoDemoStartupInstrumentedTest {

    @Test
    fun applicationStartup_installsEmbeddedSpeakerModel() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as DingqiaoApp
        val model = VoiceprintModelHelper.modelFile(app.workDir.absolutePath)

        assertTrue(
            "application startup should install the embedded speaker model: ${model.absolutePath}",
            VoiceprintModelHelper.isReady(model),
        )
    }
}
