package com.amphion.dingqiao.demo

import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar
import java.io.File

class DebugRecordsActivity : AppCompatActivity() {

    private lateinit var store: DebugRecordStore
    private lateinit var adapter: DebugRecordAdapter
    private lateinit var rv: RecyclerView
    private lateinit var tvEmpty: TextView

    private val items = mutableListOf<DebugRecordSummary>()
    private val player = PcmPlayer()
    private var playingBaseName: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_debug_records)

        store = DebugRecordStore(File(DingqiaoApp.workPath(), "debug_records"))
        rv = findViewById(R.id.rv_records)
        tvEmpty = findViewById(R.id.tv_empty)

        findViewById<MaterialToolbar>(R.id.toolbar).apply {
            setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }
        }

        adapter = DebugRecordAdapter(items) { index -> onPlay(index) }
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter
    }

    override fun onResume() {
        super.onResume()
        reload()
    }

    override fun onDestroy() {
        super.onDestroy()
        player.stop()
    }

    private fun reload() {
        items.clear()
        items.addAll(store.listRecords())
        adapter.notifyDataSetChanged()
        tvEmpty.visibility = if (items.isEmpty()) View.VISIBLE else View.GONE
        rv.visibility = if (items.isEmpty()) View.GONE else View.VISIBLE
    }

    private fun onPlay(index: Int) {
        if (index !in items.indices) return
        val item = items[index]
        if (playingBaseName == item.baseName) {
            stopPlayback()
            return
        }
        val pcm = try {
            store.readPcm(item)
        } catch (t: Throwable) {
            toast(getString(R.string.debug_record_play_failed, t.message ?: t.javaClass.simpleName))
            return
        }
        if (pcm.isEmpty()) {
            toast(getString(R.string.debug_record_play_failed, getString(R.string.debug_record_empty_audio)))
            return
        }
        playingBaseName = item.baseName
        adapter.playingBaseName = playingBaseName
        adapter.notifyDataSetChanged()
        player.play(pcm, item.sampleRate) {
            runOnUiThread { clearPlayingState() }
        }
    }

    private fun stopPlayback() {
        player.stop()
        clearPlayingState()
    }

    private fun clearPlayingState() {
        playingBaseName = null
        adapter.playingBaseName = null
        adapter.notifyDataSetChanged()
    }

    private fun toast(msg: String) {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }
}
