package com.amphion.asr.sample.eval

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import com.amphion.asr.sample.R

/**
 * 评测版入口启动页：点击「参与测试」进入评测主页 [EvalActivity]。
 *
 * 设计动机：
 * - 评测版只承载「评测数据采集」一种业务，不再承载 demo 现场识别（demo 已迁出到对外 :samples:public-demo 模块）
 * - 保留 LandingActivity 是为了让测试员看到品牌与"做什么"的引导，而不是直接被丢进列表页
 * - 若未来评测版要并入「设置」「历史」等多个入口，再把 Landing 改回多卡片布局
 *
 * Activity 不持有任何长期状态，每次跳转都是 startActivity 新 Activity，不要 set FLAG_NEW_TASK，
 * 让用户用系统返回键回到 LandingActivity。
 */
class LandingActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_landing)

        findViewById<android.view.View>(R.id.card_eval).setOnClickListener {
            startActivity(Intent(this, EvalActivity::class.java))
        }
    }
}
