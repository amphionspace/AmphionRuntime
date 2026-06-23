package com.amphion.dingqiao.demo

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.appbar.MaterialToolbar

/**
 * 自定义热词管理：写入 [DemoPrefs]，由 [MainActivity] 通过 sysGeneralLexicon 传入引擎。
 * 警务三场景预设热词仍由 SDK 默认开启，本页仅管理用户追加词。
 */
class HotwordsActivity : AppCompatActivity() {

    private val items = mutableListOf<String>()
    private lateinit var adapter: HotwordsAdapter
    private lateinit var tvCount: TextView
    private lateinit var tvEmpty: TextView
    private var configDirty = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hotwords)

        findViewById<MaterialToolbar>(R.id.toolbar).apply {
            setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }
        }

        tvCount = findViewById(R.id.tv_count)
        tvEmpty = findViewById(R.id.tv_empty)
        val rv = findViewById<RecyclerView>(R.id.rv_hotwords)
        adapter = HotwordsAdapter(items, onDelete = { idx -> deleteAt(idx) })
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        findViewById<Button>(R.id.btn_add).setOnClickListener { showAddDialog() }

        items.addAll(DemoPrefs.getUserHotwords(this))
        adapter.notifyDataSetChanged()
        refreshCount()
    }

    private fun refreshCount() {
        tvCount.text = getString(R.string.hotwords_count_label, items.size)
        tvEmpty.visibility = if (items.isEmpty()) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun deleteAt(index: Int) {
        if (index !in items.indices) return
        items.removeAt(index)
        adapter.notifyItemRemoved(index)
        DemoPrefs.setUserHotwords(this, items)
        configDirty = true
        refreshCount()
    }

    private fun showAddDialog() {
        val view = LayoutInflater.from(this).inflate(R.layout.dialog_add_hotword, null, false)
        val et = view.findViewById<EditText>(R.id.et_hotword)
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.hotwords_add_dialog_title)
            .setView(view)
            .setPositiveButton(R.string.hotwords_add_dialog_save, null)
            .setNegativeButton(R.string.hotwords_add_dialog_cancel, null)
            .create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                val text = et.text?.toString()?.trim().orEmpty()
                if (text.isEmpty() || text.length > MAX_LEN) {
                    Toast.makeText(this, R.string.hotwords_invalid, Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                if (items.any { it == text }) {
                    Toast.makeText(this, R.string.hotwords_duplicate, Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                items.add(text)
                adapter.notifyItemInserted(items.size - 1)
                DemoPrefs.setUserHotwords(this, items)
                configDirty = true
                refreshCount()
                dialog.dismiss()
            }
        }
        dialog.show()
        et.requestFocus()
    }

    override fun finish() {
        setResult(RESULT_OK, Intent().putExtra(EXTRA_HOTWORDS_CHANGED, configDirty))
        super.finish()
    }

    companion object {
        const val EXTRA_HOTWORDS_CHANGED = "hotwords_changed"
        private const val MAX_LEN = 60
    }
}
