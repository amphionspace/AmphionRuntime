# 鼎桥 Android TTS 批测语料

本目录是鼎桥 Android TTS 批测语料的唯一维护源。生成脚本统一放在 `tts/tools/android/`，不得在仓库根目录或测试工程中维护第二份源数据。

`aarHost/src/androidTest/assets/` 和 `sdk/src/androidTest/assets/` 中的文件是测试 APK 的打包副本；需要更新时，应先在本目录生成和审查，再同步到对应测试模块。

## 生成命令

```bash
python3 tts/tools/android/generate_improved_v3_sdk_stability_1000_cases.py
python3 tts/tools/android/select_improved_v3_from_v2.py
python3 tts/tools/android/generate_edge_text_200_cases.py
```

历史标注和人工复核中间结果放在 `review/`，不作为设备批测入口。
