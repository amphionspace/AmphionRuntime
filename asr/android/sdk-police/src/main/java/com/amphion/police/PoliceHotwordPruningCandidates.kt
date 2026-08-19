package com.amphion.police

/** Reversible iter250 candidate batches. These are never applied by the delivery FULL profile. */
internal object PoliceHotwordPruningCandidates {

    /**
     * UI/menu phrases that were already decoded correctly in both historical UI replay rounds.
     * Fresh iter250 FULL-vs-PRUNE_UI30 device replay is still required before promotion.
     */
    val UI30_REMOVED_TERMS: Set<String> = linkedSetOf(
        "任务管理",
        "要素管控",
        "通用辅助功能",
        "自主填报",
        "消息中心",
        "领导审批",
        "访客功能",
        "人口管理模块",
        "提醒信息",
        "任务处理信息",
        "数据统计",
        "其他模块入口",
        "任务签收",
        "任务退回",
        "任务处置",
        "表单填报",
        "任务赋能",
        "任务上图",
        "要素查看",
        "要素修改",
        "要素上图",
        "电子签名功能",
        "图片视频上传",
        "语音上传",
        "任务统计",
        "访客模式",
        "短租房屋查询",
        "短租房补录",
        "个人中心",
        "基本信息",
    )
}
