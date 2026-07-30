# ASR SDK 交付版本跟踪

`delivery/asr-sdk-release-history.json` 是 Android 与 HarmonyOS ASR SDK 的交付台账。
每条记录对应一个已经通过终检的实际交付物，保存平台版本、构建源码 commit、交付日期、
产物名和 provenance 文件哈希。记录的是产物真正使用的 source commit，不是随后登记台账的
metadata commit，避免 Git commit 自引用问题。

## 标准流程

1. 在干净分支完成版本更新、测试和源码提交，记该 commit 为 `SOURCE_COMMIT`。
2. 从 `SOURCE_COMMIT` 运行平台正式组包脚本。脚本自动读取台账，并在包内生成
   `docs/CHANGELOG.md`，列出同平台上一交付到本次 source commit 的 commit 变更。
3. 对最终交付物执行平台终检，不要从中间目录登记。
4. 用最终包内 provenance 登记交付，再单独提交台账更新：

```bash
python3 tools/delivery/asr_release_tracker.py record \
  --platform android \
  --version 0.3.3 \
  --source-commit "$SOURCE_COMMIT" \
  --delivered-at 2026-07-30 \
  --artifact amphion-dingqiao-v0.3.3-customer-20260730.zip \
  --provenance /path/to/extracted/VERSION.txt

python3 tools/delivery/asr_release_tracker.py record \
  --platform harmony \
  --version 0.2.9 \
  --source-commit "$SOURCE_COMMIT" \
  --delivered-at 2026-07-30 \
  --artifact amphion-harmony-asr-sdk-0.2.9-20260730 \
  --provenance /path/to/package/docs/BUILD_PROVENANCE.json
```

`record` 会验证版本和完整 commit 与 provenance 完全一致，重复的“平台 + 版本”会被拒绝。
若上一交付 commit 不是本次 source commit 的祖先，更新日志生成也会失败，要求先明确分支或
回移关系，不能静默生成不完整日志。
