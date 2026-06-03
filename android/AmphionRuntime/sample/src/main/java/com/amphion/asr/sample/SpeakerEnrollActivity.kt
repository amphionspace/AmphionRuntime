package com.amphion.asr.sample

import android.Manifest
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.SpeakerEnroller
import java.io.File
import java.util.concurrent.Executors
import kotlin.math.roundToInt

/**
 * 声纹管理页（单目标说话人）：录制多段注册音频、试听、删除，并据此生成/更新目标声纹。
 *
 * 录音以 16k mono 16bit WAV 存在 app 私有目录（[SpeakerProfileStore]）。声纹是所有段
 * embedding 的均值：每次录入或删除后自动重算并落盘（无需手动触发），无段时清空声纹。
 * 主页在 onResume 时重新读 target.emb，因此这里不需要回传 result。
 */
class SpeakerEnrollActivity : AppCompatActivity() {

    private lateinit var store: SpeakerProfileStore
    private val player = PcmPlayer()
    private val buildExec = Executors.newSingleThreadExecutor { r ->
        Thread(r, "speaker-enroll").apply { isDaemon = true }
    }

    private lateinit var tvStatus: TextView
    private lateinit var rv: RecyclerView
    private lateinit var tvEmpty: TextView
    private lateinit var btnRecord: Button
    private lateinit var tvThresholdValue: TextView
    private lateinit var seekThreshold: SeekBar

    private val items = mutableListOf<SegmentItem>()
    private lateinit var adapter: SpeakerSegmentAdapter

    private var recorder: AudioRecorder? = null
    private var recording = false
    private val recChunks = mutableListOf<ShortArray>()

    @Volatile
    private var building = false

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (!granted) toast(getString(R.string.enroll_no_permission))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_speaker_enroll)
        store = SpeakerProfileStore(applicationContext)

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }

        tvStatus = findViewById(R.id.tv_enroll_status)
        rv = findViewById(R.id.rv_segments)
        tvEmpty = findViewById(R.id.tv_empty)
        btnRecord = findViewById(R.id.btn_record)
        tvThresholdValue = findViewById(R.id.tv_threshold_value)
        seekThreshold = findViewById(R.id.seek_threshold)

        adapter = SpeakerSegmentAdapter(
            items = items,
            onPlay = { idx -> onPlay(idx) },
            onDelete = { idx -> onDeleteConfirm(idx) },
        )
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        btnRecord.setOnClickListener { if (recording) stopRecord() else startRecord() }
        setupThreshold()

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
        recorder = null
        player.stop()
        buildExec.shutdownNow()
    }

    /**
     * 目标人判定阈值滑块：progress 0..100 映射 [0.0, 1.0]，拖动时实时显示并落盘
     * （[SpeakerProfileStore.setThreshold] 走 apply 异步写，高频拖动安全）。主页在 onResume
     * 比对此值决定是否静默重建 engine，使新阈值在下一段识别生效。
     */
    private fun setupThreshold() {
        val t = store.getThreshold()
        seekThreshold.progress = (t * 100).roundToInt()
        tvThresholdValue.text = getString(R.string.enroll_threshold_value, t)
        seekThreshold.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar, progress: Int, fromUser: Boolean) {
                val v = progress / 100f
                tvThresholdValue.text = getString(R.string.enroll_threshold_value, v)
                if (fromUser) store.setThreshold(v)
            }

            override fun onStartTrackingTouch(sb: SeekBar) {}
            override fun onStopTrackingTouch(sb: SeekBar) {}
        })
    }

    private fun modelPath(): String =
        File(getExternalFilesDir(null), MainActivity.SPEAKER_MODEL_FILENAME).absolutePath

    private fun modelReady(): Boolean = File(modelPath()).exists()

    private fun reload() {
        val segs = store.listSegments()
        items.clear()
        segs.forEachIndexed { i, f ->
            val samples = ((f.length() - 44).coerceAtLeast(0) / 2).toInt()
            val label = getString(
                R.string.enroll_seg_label,
                i + 1,
                fmtDuration(WavIo.durationMs(samples)),
            )
            items.add(SegmentItem(f, label))
        }
        adapter.notifyDataSetChanged()
        tvEmpty.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
        updateStatus()
    }

    private fun updateStatus() {
        tvStatus.text = when {
            building -> getString(R.string.enroll_building)
            !modelReady() -> getString(R.string.ts_model_missing)
            items.isEmpty() -> getString(R.string.enroll_status_none)
            store.hasEmbedding() -> getString(R.string.enroll_status_ready, items.size)
            else -> getString(R.string.enroll_status_segments, items.size)
        }
        btnRecord.isEnabled = !building
    }

    private fun startRecord() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permLauncher.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        player.stop()
        recording = true
        synchronized(recChunks) { recChunks.clear() }
        btnRecord.setText(R.string.enroll_record_stop)
        btnRecord.setBackgroundResource(R.drawable.bg_button_recording)
        tvStatus.text = getString(R.string.enroll_recording)
        recorder = AudioRecorder(
            sampleRate = 16000,
            onPcm = { s -> synchronized(recChunks) { recChunks.add(s) } },
            onError = { msg -> runOnUiThread { toast("录音错误：$msg") } },
            gainDb = 10f,
        ).also { it.start() }
    }

    private fun stopRecord() {
        recording = false
        recorder?.stop()
        recorder = null
        btnRecord.setText(R.string.enroll_record)
        btnRecord.setBackgroundResource(R.drawable.bg_button_primary)

        val pcm = synchronized(recChunks) {
            val merged = mergeShort(recChunks)
            recChunks.clear()
            merged
        }
        if (pcm.size < 16000) { // < 1s
            toast("这段太短，已忽略")
            reload()
            return
        }
        store.addSegment(pcm)
        buildEmbedding() // 录入即自动推理，用当前所有段重算声纹
    }

    private fun onPlay(idx: Int) {
        if (idx !in items.indices) return
        val pcm = WavIo.readPcm(items[idx].file)
        player.play(pcm) { }
    }

    private fun onDeleteConfirm(idx: Int) {
        if (idx !in items.indices) return
        AlertDialog.Builder(this)
            .setTitle(R.string.enroll_delete_title)
            .setMessage(R.string.enroll_delete_msg)
            .setPositiveButton(R.string.enroll_delete_ok) { _, _ -> onDelete(idx) }
            .setNegativeButton(R.string.hotwords_add_dialog_cancel, null)
            .show()
    }

    private fun onDelete(idx: Int) {
        if (idx !in items.indices) return
        player.stop()
        store.deleteSegment(items[idx].file)
        buildEmbedding() // 删段后用剩余段自动重算（无段则清空声纹）
    }

    /** 录入/删除后自动推理：用当前所有段重算声纹并落盘；无段则清空声纹。 */
    private fun buildEmbedding() {
        val segFiles = store.listSegments()
        if (segFiles.isEmpty()) {
            store.clearEmbedding()
            reload()
            return
        }
        if (!modelReady()) {
            toast(getString(R.string.ts_model_missing))
            reload()
            return
        }
        building = true
        tvStatus.text = getString(R.string.enroll_building)
        btnRecord.isEnabled = false
        buildExec.execute {
            val ok = try {
                val floats = segFiles.map { store.readSegmentFloat(it) }
                SpeakerEnroller(modelPath()).use { enroller ->
                    val emb = enroller.enroll(floats)
                    store.saveEmbedding(emb)
                }
                true
            } catch (t: Throwable) {
                false
            }
            runOnUiThread {
                building = false
                if (!ok) toast(getString(R.string.enroll_build_failed))
                reload()
            }
        }
    }

    private fun mergeShort(chunks: List<ShortArray>): ShortArray {
        val total = chunks.sumOf { it.size }
        val out = ShortArray(total)
        var i = 0
        for (c in chunks) {
            System.arraycopy(c, 0, out, i, c.size)
            i += c.size
        }
        return out
    }

    private fun fmtDuration(ms: Long): String {
        val sec = (ms / 1000).toInt()
        return "%d:%02d".format(sec / 60, sec % 60)
    }

    private fun toast(s: String) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show()
    }
}
