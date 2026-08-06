# Harmony 目标说话人客户回归语料

该目录固定保存 2026-07-29 客户提供的三段声纹注册音频、C1～C3 三段测试音频、问题描述和原始
回放日志。它用于验证 Harmony `enableTargetSpeakerEnhancement` 的内容效果，不能用三条样例估计
FAR、FRR、CER/WER 或选择商用阈值。

## 数据分组

- `enrollment/`：同一目标说话人的远、中、近三段注册音频，评测时必须作为同一个声纹注册。
- `cases/C1.wav`：目标与非目标轮流说话，检查非目标尾音是否进入已接受文本。
- `cases/C2.wav`：目标说话时非目标插话，检查目标内容是否被混合句一起丢弃。
- `cases/C3.wav`：非目标近麦、目标远场，检查目标内容能否恢复。
- `logs/`：客户原始 SDK 回放时间线；`problem-description.txt` 是原始问题摘要。
- `manifest.json`：角色、格式、帧数、时长和 SHA-256 的固定清单。

目标说话人增强的精确业务断言为：C1、C2、C3 的最终放行文本都包含“上海”，且不包含“你好”。
生命周期仍需分别检查显式 `finish` 前没有 `isLast=true`，结束后恰好一次 `isLast`、随后一次
`onComplete`，且没有错误或跨 session 回调。

正式 ORT 真机回归使用清单驱动，runner 会把三条 `role=enrollment` 音频一次性注册为同一个声纹，
并且只把三条 `role=case` 音频送入增强链路：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir asr/test-fixtures/target-speaker-customer-cases \
  --target-speaker-manifest asr/test-fixtures/target-speaker-customer-cases/manifest.json \
  --mode target-speaker-enhancement --cycles 3 --files 0 --pace-ms 20
```

## 使用限制

这些文件包含客户真实人声和声纹注册样本。不得复制进 SDK、HAR、HAP、客户交付包、公开样例或日志
附件；公开远端仓库只有在取得客户对这些音频和日志的公开再分发授权后才能接收本目录。替换任何文件时
必须同步更新 `manifest.json`、对应证据文档和真机差分报告；不得以重新编码后的 WAV 冒充相同输入。
