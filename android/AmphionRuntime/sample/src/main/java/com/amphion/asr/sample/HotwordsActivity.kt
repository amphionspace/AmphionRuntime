package com.amphion.asr.sample

import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.appcompat.widget.Toolbar
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.AsrLanguage
import com.google.android.material.tabs.TabLayout

/**
 * 热词管理页：两个 Tab（中英 / 粤英），各自独立维护一份热词列表 + master 总开关。
 *
 * 数据流：
 * - onCreate：从 [HotwordsPrefs] 读两份列表 / master 到内存
 * - 用户操作：仅改内存中的列表 + 用 SP 即时持久化（apply 不阻塞）
 * - finish：通过 [setResult] 告知 [MainActivity] 「热词配置可能已变」，由上层决定是否重建 engine
 *
 * 不做的事（明确边界）：
 * - 不直接持有 AsrEngine / AsrSession：避免页面间状态耦合
 * - 不做导入 / 导出（FAQ 范畴，按需后补）
 * - 不持久化「上次激活的 Tab」（每次启动默认中英）
 *
 * 返回 [MainActivity] 的约定：result code RESULT_OK + extra [EXTRA_HOTWORDS_CHANGED]=true。
 * MainActivity 拿到后会重新查 [HotwordsPrefs.activeWords]，决定 重建 engine / hot-update / no-op。
 */
class HotwordsActivity : AppCompatActivity() {

    private lateinit var prefs: HotwordsPrefs

    private lateinit var tabs: TabLayout
    private lateinit var switchMaster: SwitchCompat
    private lateinit var tvCount: TextView
    private lateinit var rv: RecyclerView
    private lateinit var tvEmpty: TextView
    private lateinit var btnAdd: Button

    /** 当前 Tab 选中的语言。 */
    private var currentLang: AsrLanguage = AsrLanguage.ZH_EN

    /** 当前语言的可变列表；TabLayout 切换时整列重载。 */
    private val items: MutableList<HotwordEntry> = mutableListOf()

    private lateinit var adapter: HotwordsAdapter

    /** 用户在本次会话内是否实际改了配置；用于决定 setResult 的 EXTRA_HOTWORDS_CHANGED。 */
    private var configDirty: Boolean = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hotwords)
        prefs = HotwordsPrefs(applicationContext)

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)
        toolbar.setNavigationOnClickListener { onBackPressedDispatcher.onBackPressed() }

        tabs = findViewById(R.id.tabs)
        switchMaster = findViewById(R.id.switch_master)
        tvCount = findViewById(R.id.tv_count)
        rv = findViewById(R.id.rv_hotwords)
        tvEmpty = findViewById(R.id.tv_empty)
        btnAdd = findViewById(R.id.btn_add)

        adapter = HotwordsAdapter(
            items = items,
            onEnabledChanged = { idx, enabled -> onItemEnabledChanged(idx, enabled) },
            onDelete = { idx -> onItemDelete(idx) },
        )
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        tabs.addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) {
                currentLang = if (tab.position == 0) AsrLanguage.ZH_EN else AsrLanguage.YUE_EN
                reloadForCurrentLang()
            }
            override fun onTabUnselected(tab: TabLayout.Tab) {}
            override fun onTabReselected(tab: TabLayout.Tab) {}
        })

        switchMaster.setOnCheckedChangeListener { _, isChecked ->
            if (prefs.masterEnabled(currentLang) == isChecked) return@setOnCheckedChangeListener
            prefs.setMasterEnabled(currentLang, isChecked)
            configDirty = true
            refreshCount()
        }

        btnAdd.setOnClickListener { showAddDialog() }

        // 初始进入：默认 Tab 0 = ZH_EN；reloadForCurrentLang 在 onTabSelected 里自动调一次
        currentLang = AsrLanguage.ZH_EN
        reloadForCurrentLang()
    }

    private fun reloadForCurrentLang() {
        items.clear()
        items.addAll(prefs.load(currentLang))
        adapter.notifyDataSetChanged()
        switchMaster.setOnCheckedChangeListener(null)
        switchMaster.isChecked = prefs.masterEnabled(currentLang)
        switchMaster.setOnCheckedChangeListener { _, isChecked ->
            if (prefs.masterEnabled(currentLang) == isChecked) return@setOnCheckedChangeListener
            prefs.setMasterEnabled(currentLang, isChecked)
            configDirty = true
            refreshCount()
        }
        refreshCount()
    }

    private fun refreshCount() {
        val total = items.size
        val enabled = items.count { it.enabled }
        tvCount.text = getString(R.string.hotwords_count_label, total, enabled)
        tvEmpty.visibility = if (total == 0) android.view.View.VISIBLE else android.view.View.GONE
    }

    private fun onItemEnabledChanged(index: Int, enabled: Boolean) {
        if (index !in items.indices) return
        val old = items[index]
        if (old.enabled == enabled) return
        items[index] = old.copy(enabled = enabled)
        prefs.save(currentLang, items)
        configDirty = true
        refreshCount()
    }

    private fun onItemDelete(index: Int) {
        if (index !in items.indices) return
        items.removeAt(index)
        adapter.notifyItemRemoved(index)
        prefs.save(currentLang, items)
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
                if (text.isEmpty() || text.length > HotwordsPrefs.SUGGESTED_MAX_LEN) {
                    Toast.makeText(this, R.string.hotwords_invalid, Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                if (items.any { it.text == text }) {
                    Toast.makeText(this, R.string.hotwords_duplicate, Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                items.add(HotwordEntry(text = text, enabled = true))
                adapter.notifyItemInserted(items.size - 1)
                prefs.save(currentLang, items)
                configDirty = true
                refreshCount()
                dialog.dismiss()
            }
        }
        dialog.show()
        et.requestFocus()
    }

    override fun finish() {
        // setResult 必须在 super.finish() 之前；让 MainActivity 走 ActivityResult 回调
        val data = Intent().putExtra(EXTRA_HOTWORDS_CHANGED, configDirty)
        setResult(RESULT_OK, data)
        super.finish()
    }

    companion object {
        const val EXTRA_HOTWORDS_CHANGED: String = "hotwords_changed"
    }
}
