package com.amphion.dingqiao.demo

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.amphion.dingqiao.AudioInfo
import com.amphion.dingqiao.DINGQIAO_VOICEPRINT_MAX_SEC
import com.amphion.dingqiao.DINGQIAO_VOICEPRINT_MAX_SAMPLES
import com.amphion.dingqiao.DINGQIAO_VOICEPRINT_MIN_SEC
import com.amphion.dingqiao.DINGQIAO_VOICEPRINT_MIN_SAMPLES
import com.amphion.dingqiao.SpeechRecognizeSdk
import com.amphion.dingqiao.VoiceprintRegisterParams
import com.google.android.material.appbar.MaterialToolbar
import java.io.File
import java.util.Locale
import java.util.concurrent.Executors

/**
 * 声纹注册页：录制 3~5 段样本，调用 [SpeechRecognizeSdk.registerVoiceprint]。
 */
class VoiceprintEnrollActivity : AppCompatActivity() {

    private lateinit var store: EnrollSampleStore
    private lateinit var tvStatus: TextView
    private lateinit var tvEmpty: TextView
    private lateinit var rv: RecyclerView
    private lateinit var btnImportModel: Button
    private lateinit var btnRecord: Button
    private lateinit var btnRegister: Button
    private lateinit var btnDeleteVoiceprint: Button
    private lateinit var tvRegisteredId: TextView

    private val items = mutableListOf<File>()
    private lateinit var adapter: VoiceprintSampleAdapter
    private val player = PcmPlayer()
    private val worker = Executors.newSingleThreadExecutor()

    private var recorder: AudioRecorder? = null
    private var recording = false
    private val recChunks = mutableListOf<ShortArray>()

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (!granted) toast(getString(R.string.enroll_no_permission))
    }

    private val importModelLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri == null) return@registerForActivityResult
        worker.execute {
            val ok = VoiceprintModelHelper.importFromUri(this, DingqiaoApp.workPath(), uri)
            runOnUiThread {
                if (ok) {
                    toast(getString(R.string.vp_model_import_ok))
                    reload()
                } else {
                    toast(getString(R.string.vp_model_import_failed))
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_voiceprint_enroll)

        store = EnrollSampleStore(File(DingqiaoApp.workPath(), "enroll_samples"))
        tvStatus = findViewById(R.id.tv_status)
        tvEmpty = findViewById(R.id.tv_empty)
        rv = findViewById(R.id.rv_samples)
        btnImportModel = findViewById(R.id.btn_import_model)
        btnRecord = findViewById(R.id.btn_record)
        btnRegister = findViewById(R.id.btn_register)
        btnDeleteVoiceprint = findViewById(R.id.btn_delete_voiceprint)
        tvRegisteredId = findViewById(R.id.tv_registered_id)

        findViewById<MaterialToolbar>(R.id.toolbar).apply {
            setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }
        }

        adapter = VoiceprintSampleAdapter(items, onPlay = { idx -> onPlay(idx) }, onDelete = { idx -> onDelete(idx) })
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        btnImportModel.setOnClickListener {
            importModelLauncher.launch(arrayOf("application/octet-stream", "*/*"))
        }
        btnRecord.setOnClickListener { if (recording) stopRecord() else startRecord() }
        btnRegister.setOnClickListener { registerVoiceprint() }
        btnDeleteVoiceprint.setOnClickListener { confirmDeleteVoiceprint() }

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }

        reload()
    }

    override fun onDestroy() {
        super.onDestroy()
        recorder?.stop()
        player.stop()
        worker.shutdownNow()
    }

    private fun reload() {
        items.clear()
        items.addAll(store.listSamples())
        adapter.notifyDataSetChanged()
        tvEmpty.visibility = if (items.isEmpty()) android.view.View.VISIBLE else android.view.View.GONE
        rv.visibility = if (items.isEmpty()) android.view.View.GONE else android.view.View.VISIBLE
        tvStatus.text = getString(R.string.enroll_status, items.size)
        btnRegister.isEnabled = items.size in DINGQIAO_VOICEPRINT_MIN_SAMPLES..DINGQIAO_VOICEPRINT_MAX_SAMPLES
        val registeredId = VoiceprintHelper.registeredId(this)
        if (registeredId.isNullOrBlank()) {
            tvRegisteredId.visibility = android.view.View.GONE
            btnDeleteVoiceprint.visibility = android.view.View.GONE
        } else {
            tvRegisteredId.visibility = android.view.View.VISIBLE
            tvRegisteredId.text = getString(R.string.enroll_registered_id, registeredId)
            btnDeleteVoiceprint.visibility = android.view.View.VISIBLE
        }
    }

    private fun startRecord() {
        if (items.size >= DINGQIAO_VOICEPRINT_MAX_SAMPLES) {
            toast(getString(R.string.enroll_status, items.size))
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        recording = true
        recChunks.clear()
        btnRecord.setText(R.string.enroll_record_stop)
        tvStatus.text = getString(R.string.enroll_recording)
        recorder = AudioRecorder(onPcm = { recChunks += it }, onError = { msg -> toast(msg) }).also { it.start() }
    }

    private fun stopRecord() {
        recording = false
        recorder?.stop()
        recorder = null
        btnRecord.setText(R.string.enroll_record)
        val pcm = merge(recChunks)
        recChunks.clear()
        if (pcm.isEmpty()) {
            reload()
            return
        }
        store.addSample(pcm)
        reload()
    }

    private fun onPlay(index: Int) {
        if (index !in items.indices) return
        val pcm = store.readPcm(items[index])
        player.play(pcm) { }
    }

    private fun onDelete(index: Int) {
        if (index !in items.indices) return
        AlertDialog.Builder(this)
            .setTitle(R.string.enroll_delete_title)
            .setMessage(R.string.enroll_delete_msg)
            .setPositiveButton(R.string.enroll_delete_ok) { _, _ ->
                store.deleteSample(items[index])
                if (VoiceprintHelper.registeredId(this) != null) {
                    VoiceprintHelper.deleteRegisteredIfAny(this)
                }
                reload()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun confirmDeleteVoiceprint() {
        val id = VoiceprintHelper.registeredId(this) ?: return
        AlertDialog.Builder(this)
            .setTitle(R.string.vp_delete_title)
            .setMessage(getString(R.string.vp_delete_msg) + "\n\n$id")
            .setPositiveButton(R.string.vp_delete_ok) { _, _ -> deleteVoiceprintNow() }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    private fun deleteVoiceprintNow() {
        btnDeleteVoiceprint.isEnabled = false
        worker.execute {
            try {
                val id = VoiceprintHelper.deleteRegistered(this@VoiceprintEnrollActivity)
                runOnUiThread {
                    toast(getString(R.string.vp_delete_success, id ?: ""))
                    reload()
                }
            } catch (t: Throwable) {
                val msg = t.message ?: t.javaClass.simpleName
                runOnUiThread {
                    toast(getString(R.string.vp_delete_failed, msg))
                    btnDeleteVoiceprint.isEnabled = true
                    reload()
                }
            }
        }
    }

    private fun registerVoiceprint() {
        if (items.size !in DINGQIAO_VOICEPRINT_MIN_SAMPLES..DINGQIAO_VOICEPRINT_MAX_SAMPLES) return
        val modelFile = VoiceprintModelHelper.modelFile(DingqiaoApp.workPath())
        if (!VoiceprintModelHelper.isReady(modelFile)) {
            toast(
                if (modelFile.exists() && !modelFile.canRead()) {
                    getString(R.string.vp_model_unreadable)
                } else {
                    getString(R.string.vp_model_missing)
                },
            )
            return
        }
        btnRegister.isEnabled = false
        tvStatus.text = getString(R.string.enroll_registering)
        val invalidSampleMessage = firstInvalidSampleMessage()
        if (invalidSampleMessage != null) {
            toast(invalidSampleMessage)
            tvStatus.text = invalidSampleMessage
            btnRegister.isEnabled = true
            return
        }
        worker.execute {
            try {
                VoiceprintHelper.deleteRegisteredIfAny(this@VoiceprintEnrollActivity)
                val result = SpeechRecognizeSdk.registerVoiceprint(
                    VoiceprintRegisterParams(
                        samplePaths = items.map { it.absolutePath },
                        audioInfo = AudioInfo(),
                    ),
                )
                val id = result.voiceprintId.keys.first()
                runOnUiThread {
                    DemoPrefs.setVoiceprintId(this, id)
                    toast(getString(R.string.enroll_success, id))
                    finish()
                }
            } catch (t: Throwable) {
                val msg = t.message ?: t.javaClass.simpleName
                runOnUiThread {
                    toast(getString(R.string.enroll_failed, msg))
                    reload()
                }
            }
        }
    }

    private fun firstInvalidSampleMessage(): String? {
        for ((index, file) in items.withIndex()) {
            val durationSec = sampleDurationSec(file)
            if (durationSec < DINGQIAO_VOICEPRINT_MIN_SEC || durationSec > DINGQIAO_VOICEPRINT_MAX_SEC) {
                return getString(
                    R.string.enroll_sample_duration_invalid,
                    index + 1,
                    file.name,
                    String.format(Locale.getDefault(), "%.1f", durationSec),
                    DINGQIAO_VOICEPRINT_MIN_SEC,
                    DINGQIAO_VOICEPRINT_MAX_SEC,
                )
            }
        }
        return null
    }

    private fun sampleDurationSec(file: File): Double =
        file.length().coerceAtLeast(0L).toDouble() / BYTES_PER_SECOND

    private fun merge(chunks: List<ShortArray>): ShortArray {
        val total = chunks.sumOf { it.size }
        if (total == 0) return ShortArray(0)
        val out = ShortArray(total)
        var off = 0
        for (c in chunks) {
            System.arraycopy(c, 0, out, off, c.size)
            off += c.size
        }
        return out
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    private companion object {
        private const val SAMPLE_RATE = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private const val BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE.toDouble()
    }
}
