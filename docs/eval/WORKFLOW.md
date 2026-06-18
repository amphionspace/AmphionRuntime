# Amphion ASR 评估工作流

本文档分两部分：

- 测试员手册：拿到 APK + token 后该怎么做
- 工程师手册：从数据到 WER 报告该怎么跑

> 术语对照：app UI 上对测试员展示「准确率」（= 1 − WER），数值越高越好；
> meta.json schema、后台脚本、本文档工程师章节仍统一使用 WER。
> 例：UI 看到「准确率 91.7%」== schema 里 `on_device_wer_estimate: 0.083`。

## 一、测试员手册

### 1.1 准备

设备：

- Android 7.0+
- arm64-v8a CPU
- 至少 100 MB 可用存储（10 句录音约 5 MB；75 句录两遍约 75 MB）
- 麦克风允许使用

从工程师拿到：

1. APK 安装包
2. （可选）Bearer token + 服务器 URL —— 用于 HTTP 自动上传

### 1.2 首次启动

1. 安装 APK，打开「Amphion ASR」
2. 启动页两个卡片选「评估数据采集」
3. 弹出昵称对话框，填真名或工号（建议英文 / 拼音）。同一昵称在不同手机会派生同一 tester_id，方便后台聚合
4. 系统授予录音权限

### 1.3 配置上传

如果工程师给了 token：

1. 右上角菜单 → 上传服务器配置
2. 填服务器 URL（如 https://eval.example.com）
3. 填 Bearer token（工程师私发给你的字符串）
4. 「录音保存后自动上传」默认开，建议保留
5. 保存

如果没有 token，先用「离线模式」：录音都保存在本地，事后用菜单 → 导出 zip 离线兜底，把 zip 分享给工程师。

### 1.4 录一句

1. 主列表按分类展示 75 句；点击任意一句进入录音页
2. 顶部展示参考文本
3. 中部可填环境信息：地点（办公室 / 高铁 / 户外）、噪声等级、备注
4. 底部「点击开始录音」按钮：
   - 第一次点 = 开始
   - 第二次点 = 停止
5. 停止后页面原地展示「三件套」：
   - 估算 WER（字符级，仅供参考）
   - hypothesis 行（带颜色 diff）
   - 「播放」按钮（回放录音）
6. 满意 → 点「保存并下一句」（自动跳转）；不满意 → 点「重录」

### 1.4.bis 自由录音（先录 → 再校对）

如果内置 75 句不能覆盖你的业务场景：

1. 在主列表最顶部，点「+ 自由录音」卡片
2. 直接进入录音页（不需要先输入文本）
3. 点开始按钮 → 想到啥念啥 → 点停止
4. 识别结果会自动填入下方输入框作为 reference 草稿
5. 校对输入框里的文字（通常只需改一两个字），确认就是你刚才念的
6. 点「保存」→ 完成

约定：

- 相同 reference 文本会聚合到同一条目；多人录同一句、同一人多次录，后台都能对比 WER（sentence_id 按 reference 内容派生）
- 一旦校对保存的 reference 就不能在 app 内编辑；想换 reference = 新建一条录音
- 想丢弃整条「自由录音」条目：进详情页删除所有未上传的 attempts；已上传的请联系工程师从服务端清理
- 校对很重要：识别结果只是草稿，请确认它就是你刚才念的；不要懒得改直接保存，否则数据会失真

### 1.5 看历史

主列表每个 item 显示「已录 N 次 · 估算 WER X% · 已上传 M/N」。点击已有录音的 item → 进入详情页：

- 每次 attempt 的 diff + 估算 WER
- 「播放」按钮逐条听
- 未上传的 attempt 可删除（已上传的不可删，需联系工程师从服务端清理）
- 「再录一次」按钮 → 新增 attempt

### 1.6 上传状态

主列表顶部状态条显示「待上传 N · 已上传 M · 失败 K」。点击「立即同步」会主动触发一轮上传（含失败重试）。

正常状态：

- 录完句子后 1-3 秒内自动上传
- 网络抖动会自动重试，无需手动干预
- 失败的录音会出现在「失败 K」计数里，点「立即同步」可手动重试

异常情况：

- 状态条显示「未配置上传服务器」→ 点配置或菜单去填
- 长时间「上传中…」→ 检查网络后再点立即同步

### 1.7 切换测试员

菜单 → 切换测试员。会清空当前 nickname，下次启动评估页时重新填。注意：

- 本地已录的数据不会删除
- 但新 tester 看不到旧 tester 的录音
- 适用于「同一设备多人共用」的场景

### 1.8 常见问题

录音突然结束：句子超过 20 秒会被引擎自动 endpoint。不影响录音保存，但识别可能只覆盖前段。建议每句 < 15 秒。

弹「现场识别不可用」：本机没有 push ASR 模型，仅保存录音，不算估算 WER。后台脚本仍可跑权威 WER。

弹「保存失败：rename 异常」：极少见，通常是存储满了。清理存储后重试。

录音播放时手机变烫：MediaPlayer 在长录音上会有点 CPU 占用。短录音 < 10 秒 不会有问题。

## 二、工程师手册

### 2.1 准备测试集

种子测试集已经在 assets/eval-set/sentences.json 里（75 句 6 类）。

要扩展或替换，编辑该 JSON（schema 见 docs/eval/SCHEMA.md），然后：

```bash
# 方案 A：重新打包 APK
./gradlew :samples:public-demo:assembleDebug

# 方案 B：adb push 覆盖（不需要重打包）
adb push my-sentences.json /sdcard/Android/data/com.amphion.asr.sample/files/asr-eval-set/sentences.json
```

外部覆盖比内置版本优先级高。

### 2.2 发 Token

按 docs/eval/SERVER_SPEC.md 部署服务端，然后：

```bash
openssl rand -hex 24
# 输出一行 hex 字符串，分发给单个测试员
```

每个 tester 一个独立 token（推荐）；服务端 TOKEN_TO_TESTER dict 配置好映射后重启。

### 2.3 拉取数据

服务端落盘后：

```bash
rsync -avz user@eval-server:/var/lib/amphion-eval/ ./eval-data/
```

或者，测试员用 zip 导出兜底时，工程师收到 zip 后：

```bash
mkdir -p ./eval-data
unzip eval_alice_20260519_120000.zip -d ./eval-data/
```

两种来源的目录结构镜像，可以用同一份 eval_wer.py 跑。

### 2.4 跑 WER 报告

```bash
# 1. 安装依赖
pip install jiwer sherpa-onnx

# 2. 跑批量 WER
python asr/tools/eval_wer.py \
  --data-root ./eval-data \
  --model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --output ./report \
  --mode streaming

# 输出：
# ./report/report.json        # 机器可读
# ./report/report.md           # 人类可读
# ./report/per_recording.csv   # 每条记录的明细
```

报告内容：

- 总体 WER（按词级，使用 jiwer）
- 按 tester / category / noise_level / device.manufacturer / model_version 分组的 WER
- 与每条录音的 on_device_wer_estimate 对比，标注差异较大的样本

### 2.5 调试单条录音

```bash
# 看某条录音的 meta
cat ./eval-data/alice/zh_en_mixed_005/0bf8.../meta.json | jq

# 听音频
afplay ./eval-data/alice/zh_en_mixed_005/0bf8.../audio.wav      # macOS
aplay ./eval-data/alice/zh_en_mixed_005/0bf8.../audio.wav        # Linux

# 重跑单条识别
sherpa-onnx-offline \
  --model asr/tools/demo-model/zipformer_L_zh_en \
  ./eval-data/alice/zh_en_mixed_005/0bf8.../audio.wav
```

### 2.6 清理已上传数据

服务端：

```bash
# 删除某 tester 某 sentence 的全部 attempt
rm -rf /var/lib/amphion-eval/<tester_id>/<sentence_id>/

# 不要直接删 audio.wav 留 meta.json；要删整目录
```

客户端不会主动删已上传的本地副本。如果客户端存储紧张，让测试员用菜单的「清理 7 天前已上传录音」（TODO 项，本期未实现）。

### 2.7 升级 schema

按以下顺序操作，避免破坏老数据：

1. 改 docs/eval/SCHEMA.md，bump schema_version
2. 改 docs/eval/SERVER_SPEC.md 错误码表 + 示例
3. 改客户端 RecordingMeta，bump CURRENT_SCHEMA_VERSION 并保留向后兼容（旧 schema 仍可读）
4. 改服务端 SUPPORTED_SCHEMA_VERSIONS = {1, 2}
5. 发新 APK
6. 待 95% 设备升级后，服务端从 SUPPORTED_SCHEMA_VERSIONS 移除老版本

### 2.8 性能与扩容估算

| 维度 | 单机 FastAPI（参考实现） | 备注 |
| --- | --- | --- |
| 单条上传延迟 | 200-800 ms | 取决于网络与磁盘 |
| 单进程并发 | ~8 | IO 瓶颈，CPU 不饱和 |
| 单条存储 | ~250 KB | 5 秒 16kHz 16-bit mono WAV |
| 75 句 × 1 次 × 20 人 | ~375 MB | 一个迭代周期 |
| 75 句 × 5 次 × 20 人 | ~1.9 GB | 一个 release 周期 |

不需要数据库；按 tester / sentence / recording 三级目录就够用。

### 2.9 数据隐私

- 录音内容是用户念的「评估测试集句子」，不是任意自由语音，敏感度低
- tester_id 是 sha1(nickname)[:12]，无法反推真实身份
- 服务端 token 与 tester_id 严格映射，token 泄露只影响单个测试员的数据
- 任何长期保留的数据建议加密磁盘 + 严格 ACL（这是部署事，不在协议层）
