package com.amphion.asr.sample.eval

import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.Toolbar
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.amphion.asr.sample.R
import com.amphion.asr.sample.eval.data.RecordingStore
import com.amphion.asr.sample.eval.data.SentenceRepository
import com.amphion.asr.sample.eval.data.TesterPrefs
import com.amphion.asr.sample.eval.model.RecordingMeta
import com.amphion.asr.sample.eval.model.Sentence
import com.amphion.asr.sample.eval.playback.AudioPlayer

/**
 * 句子详情页：展示该 sentence 下当前 tester 的所有 attempts。
 *
 * 是「测试员价值感受」三件套的核心载体：
 * - 回放任一次录音 → 主观判断录音质量
 * - 看 hypothesis 与 reference 的字符级 diff → 区分"自己念错"vs"模型识错"
 * - 看每次 attempt 的估算 WER → 追"成绩单"
 * - 删除未上传的不满意 attempt（已上传禁删）
 *
 * 顶部 toolbar 返回 = finish；底部"再录一次" = 跳 RecordSentenceActivity。
 */
class SentenceDetailActivity : AppCompatActivity() {

    private lateinit var prefs: TesterPrefs
    private lateinit var store: RecordingStore
    private lateinit var repo: SentenceRepository
    private lateinit var sentence: Sentence

    private lateinit var adapter: AttemptListAdapter
    private lateinit var rv: RecyclerView
    private val player = AudioPlayer(
        onError = { msg -> Toast.makeText(this, msg, Toast.LENGTH_SHORT).show() }
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_sentence_detail)

        val sentenceId = intent.getStringExtra(EXTRA_SENTENCE_ID)
        if (sentenceId.isNullOrEmpty()) {
            finish()
            return
        }
        prefs = TesterPrefs(this)
        store = RecordingStore(this)
        repo = SentenceRepository.load(this)
        sentence = repo.manifest.findSentence(sentenceId) ?: run { finish(); return }

        val toolbar = findViewById<Toolbar>(R.id.toolbar)
        setSupportActionBar(toolbar)
        supportActionBar?.apply {
            title = getString(R.string.eval_detail_title)
            setDisplayHomeAsUpEnabled(true)
        }
        toolbar.setNavigationOnClickListener { finish() }

        findViewById<TextView>(R.id.tv_reference).text = sentence.text

        adapter = AttemptListAdapter(
            reference = sentence.text,
            onPlay = ::onPlay,
            onDelete = ::onDelete,
        )
        rv = findViewById(R.id.rv_attempts)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        findViewById<android.widget.Button>(R.id.btn_add_attempt).setOnClickListener {
            startActivity(RecordSentenceActivity.intent(this, sentence.id))
        }

        lifecycle.addObserver(player)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val list = store.listAttempts(prefs.testerId(), sentence.id)
        adapter.refresh(list)
    }

    private fun onPlay(meta: RecordingMeta) {
        val f = store.audioFile(prefs.testerId(), meta.sentenceId, meta.recordingId)
        if (!f.isFile) {
            Toast.makeText(this, "音频文件不存在", Toast.LENGTH_SHORT).show()
            return
        }
        if (player.isPlaying && player.loadedPath == f.absolutePath) {
            player.pause()
            return
        }
        player.play(f)
    }

    private fun onDelete(meta: RecordingMeta) {
        if (meta.upload.isUploaded) {
            Toast.makeText(this, R.string.eval_detail_delete_blocked_uploaded, Toast.LENGTH_SHORT).show()
            return
        }
        if (meta.upload.isInflight) {
            Toast.makeText(this, R.string.eval_detail_delete_blocked_uploading, Toast.LENGTH_SHORT).show()
            return
        }
        AlertDialog.Builder(this)
            .setMessage(R.string.eval_detail_delete_confirm)
            .setPositiveButton(android.R.string.ok) { _, _ ->
                store.deleteAttempt(prefs.testerId(), meta.sentenceId, meta.recordingId)
                refresh()
            }
            .setNegativeButton(android.R.string.cancel, null)
            .show()
    }

    companion object {
        private const val EXTRA_SENTENCE_ID = "sentence_id"

        fun intent(ctx: Context, sentenceId: String): Intent =
            Intent(ctx, SentenceDetailActivity::class.java).apply {
                putExtra(EXTRA_SENTENCE_ID, sentenceId)
            }
    }
}
