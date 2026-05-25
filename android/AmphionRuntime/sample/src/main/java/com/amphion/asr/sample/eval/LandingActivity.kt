package com.amphion.asr.sample.eval

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.amphion.asr.sample.MainActivity
import com.amphion.asr.sample.R

/**
 * 入口启动页：让用户在「Demo 现场识别」与「评估收集」之间二选一。
 *
 * 设计动机：原 MainActivity 是面向开发者的"实时识别 demo"，新功能是"测试员评估数据收集"，
 * 二者的工作流完全不同；做成 landing 二选一比塞到一个菜单里更清晰，避免误操作。
 *
 * Activity 不持有任何长期状态，每次跳转都是 startActivity 新 Activity，不要 set FLAG_NEW_TASK，
 * 让用户用系统返回键回到 LandingActivity。
 */
class LandingActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_landing)

        findViewById<android.view.View>(R.id.card_demo).setOnClickListener {
            startActivity(Intent(this, MainActivity::class.java))
        }
        findViewById<android.view.View>(R.id.card_eval).setOnClickListener {
            startActivity(Intent(this, EvalActivity::class.java))
        }
    }
}
