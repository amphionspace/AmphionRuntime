package com.lits.tts.sample

import android.content.Context
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.view.LayoutInflater
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.lifecycle.ViewModelProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class SampleScreenDeviceTest {
    @Test fun mixedModeStartsWithPhilosophyText() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity {
                val text = it.findViewById<EditText>(R.id.edit_input).text.toString()
                assertTrue("Mixed demo should show the philosophy preset", text.startsWith("清晨醒来"))
                assertTrue(text.contains("freedom"))
                assertEquals(SampleTexts.forLanguage("zh-en"), text)
            }
        }
    }

    @Test fun bothScreenLayoutsExposeMemoryAndAllActions() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        for (size in listOf(Configuration.SCREENLAYOUT_SIZE_SMALL, Configuration.SCREENLAYOUT_SIZE_NORMAL)) {
            val config = Configuration(context.resources.configuration)
            config.screenLayout = (config.screenLayout and Configuration.SCREENLAYOUT_SIZE_MASK.inv()) or size
            val themed = android.view.ContextThemeWrapper(context.createConfigurationContext(config), R.style.Theme_LitsTtsSample)
            val view = LayoutInflater.from(themed).inflate(R.layout.activity_main, null)
            assertNotNull(view.findViewById<TextView>(R.id.text_memory))
            for (id in listOf(R.id.button_synthesize, R.id.button_sdk_playback, R.id.button_stop,
                R.id.button_play, R.id.button_save, R.id.button_warmup)) {
                assertNotNull(view.findViewById<Button>(id))
            }
        }
    }

    @Test fun pageRecreationRetainsRequestInputsAndResult() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            lateinit var original: TtsSampleViewModel
            scenario.onActivity { original = ViewModelProvider(it)[TtsSampleViewModel::class.java] }
            waitFor(scenario) { !it.state.value!!.busy && it.state.value!!.log.contains("onComplete requestId=warmup-") }
            val text = "清晨的阳光照进窗户，桌上的茶还冒着热气。Hello, welcome to the harbour."
            scenario.onActivity {
                it.findViewById<EditText>(R.id.edit_input).setText(text)
                it.findViewById<Button>(R.id.button_synthesize).performClick()
                it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            }
            scenario.recreate()
            scenario.onActivity {
                assertSame(original, ViewModelProvider(it)[TtsSampleViewModel::class.java])
                assertEquals(text, it.findViewById<EditText>(R.id.edit_input).text.toString())
                it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
            }
            waitFor(scenario) { it.state.value!!.canPlay }
            scenario.recreate()
            scenario.onActivity {
                assertTrue(it.findViewById<Button>(R.id.button_play).isEnabled)
                assertTrue(it.findViewById<Button>(R.id.button_save).isEnabled)
                assertFalse(original.state.value!!.log.contains("onStop requestId=synth-"))
                assertFalse(original.state.value!!.log.contains("onError"))
                assertNotNull(original.state.value!!.memory)
            }
        }
    }

    private fun waitFor(scenario: ActivityScenario<MainActivity>, predicate: (TtsSampleViewModel) -> Boolean) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(45)
        while (System.nanoTime() < deadline) {
            var ready = false
            scenario.onActivity { ready = predicate(ViewModelProvider(it)[TtsSampleViewModel::class.java]) }
            if (ready) return
            Thread.sleep(50)
        }
        fail("timed out waiting for sample state")
    }
}
