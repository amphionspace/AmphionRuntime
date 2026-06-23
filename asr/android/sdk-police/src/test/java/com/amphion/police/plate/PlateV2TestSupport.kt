package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import java.io.BufferedReader
import java.io.FileReader

/** V2 测试共用：从 assets 加载知识库 + 读音表（base 谐音表 + V2 补充表）。 */

internal fun loadKnowledgeBase(): PlateKnowledgeBase {
    val kbFile = TestAssets.resolve(PlateKnowledgeBase.ASSET_PATH)
    return BufferedReader(FileReader(kbFile)).use { PlateKnowledgeBase.loadFromReader(it) }
}

internal fun loadReadingMap(kb: PlateKnowledgeBase): PlateReadingMap {
    val base = BufferedReader(FileReader(TestAssets.resolve(PlateReadingMap.ASSET_PATH)))
    val supplement = BufferedReader(FileReader(TestAssets.resolve(PlateReadingMap.SUPPLEMENT_ASSET_PATH)))
    return base.use { b -> supplement.use { s -> PlateReadingMap.loadFromReaders(listOf(b, s), kb) } }
}
