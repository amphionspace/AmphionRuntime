package com.lits.tts.sample

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.RadioGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.ViewModelProvider

/** View binding only. Engine and request lifetime belong to the retained model. */
class MainActivity : AppCompatActivity() {
    private lateinit var model: TtsSampleViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Android selects layout-small automatically; both layouts share this binding.
        setContentView(R.layout.activity_main)
        setSupportActionBar(findViewById<Toolbar>(R.id.toolbar))
        supportActionBar?.setDisplayShowTitleEnabled(false)
        model = ViewModelProvider(this)[TtsSampleViewModel::class.java]

        val text = findViewById<EditText>(R.id.edit_input)
        val chunk = findViewById<EditText>(R.id.edit_chunk_size)
        val queue = findViewById<EditText>(R.id.edit_pcm_queue_capacity)
        val speed = findViewById<EditText>(R.id.edit_speed)
        val language = findViewById<RadioGroup>(R.id.group_mode)
        text.setText(model.input.text)
        chunk.setText(model.input.chunkSize)
        queue.setText(model.input.pcmQueueCapacity)
        speed.setText(model.input.speed)
        language.check(if (model.input.language == "en-US") R.id.radio_mode_en else R.id.radio_mode_mixed)
        fun saveInput() = model.updateInput(model.input.copy(
            text = text.text.toString(), chunkSize = chunk.text.toString(),
            pcmQueueCapacity = queue.text.toString(), speed = speed.text.toString(),
        ))
        listOf(text, chunk, queue, speed).forEach { it.doAfterTextChanged { saveInput() } }
        language.setOnCheckedChangeListener { _, id ->
            val selected = if (id == R.id.radio_mode_en) "en-US" else "zh-en"
            if (selected != model.input.language) {
                model.selectLanguage(selected)
                text.setText(model.input.text)
                text.setSelection(0)
            }
        }

        val synthesize = findViewById<Button>(R.id.button_synthesize)
        val speak = findViewById<Button>(R.id.button_sdk_playback)
        val warmup = findViewById<Button>(R.id.button_warmup)
        val play = findViewById<Button>(R.id.button_play)
        val save = findViewById<Button>(R.id.button_save)
        val stop = findViewById<Button>(R.id.button_stop)
        synthesize.setOnClickListener { model.synthesize() }
        speak.setOnClickListener { model.speak() }
        warmup.setOnClickListener { model.submitWarmup() }
        play.setOnClickListener { model.playLastAudio() }
        save.setOnClickListener { model.saveLastAudio() }
        stop.setOnClickListener { model.stopCurrentWork() }

        val status = findViewById<TextView>(R.id.text_status)
        val metrics = findViewById<TextView>(R.id.text_metrics)
        val log = findViewById<TextView>(R.id.text_log)
        val memory = findViewById<TextView>(R.id.text_memory)
        val progress = findViewById<ProgressBar>(R.id.progress_busy)
        model.state.observe(this) { state ->
            status.text = state.status
            metrics.text = state.metrics
            log.text = state.log
            memory.text = state.memory?.let {
                getString(R.string.memory_usage, it.rssKb / 1024.0, it.peakRssKb / 1024.0)
            } ?: getString(R.string.memory_pending)
            synthesize.isEnabled = !state.busy
            speak.isEnabled = !state.busy
            warmup.isEnabled = !state.busy
            play.isEnabled = state.canPlay
            save.isEnabled = state.canPlay
            stop.isEnabled = state.canStop
            listOf(chunk, queue, speed).forEach { it.isEnabled = !state.busy }
            for (i in 0 until language.childCount) language.getChildAt(i).isEnabled = !state.busy
            progress.visibility = if (state.busy) View.VISIBLE else View.GONE
        }
        model.initialize()
    }

    override fun onStart() {
        super.onStart()
        model.startMemoryMonitoring()
    }

    override fun onStop() {
        model.stopMemoryMonitoring()
        super.onStop()
    }
}
