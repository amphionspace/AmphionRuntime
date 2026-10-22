# Amphion 鸿蒙 App 协作进度

本文件给接手的 agent 用：先读「当前状态」和「待处理」，做完一项就把 `[ ]` 改成 `[x]`，并在「变更记录」追加一行（日期、做了什么、证据位置）。不要在这里写 API Key、授权文件内容、设备标识（UDID/ODID/SN）或签名口令。

**版本规则（用户 10-21 要求）**：每次装机/交付的包只要有变化，`AppScope/app.json5` 的 `versionName` 末位加一、`versionCode` 加一，并在 `CHANGELOG.md` 记录变化和装机包 sha256 前缀。当前 `1.0.2`。

## 目标

一个面向正式使用的鸿蒙 App（品牌 Amphion，界面不出现客户名、Demo/测试字样）：

- 只保留两项能力：**声纹注册**、**目标说话人识别**（只转写本人语音，旁人语音过滤）。
- 同一页面整合 **端侧离线**（AmphionRuntime 鸿蒙 SDK，全程离线）与 **云端在线**（私有化云端服务）。
- **页面不让用户感知端侧/云端**（用户 2026-10-21 要求）：主页面、声纹面板、提示与错误文案都不出现「端侧/云端/离线/在线」；选择只放在右上角弱化的「⋯」菜单里（识别模式「标准」=端侧、「增强」=云端）；两种模式交互完全一致。
- 声纹注册统一：一次录三段（远/中/近，各 5–8 秒），同一份录音同时注册端侧与云端，界面上只有「一个声纹」，不区分两端。
- Speaker VAD 两端默认开启。
- 主界面以转写内容为主；声纹注册收在右上角「声纹」胶囊打开的底部面板里。

## 代码位置

- 工程：`asr/harmony-apps/amphion-voice/`（分支 `feat/harmony-target-speaker-app`，尚未提交）。
- 页面：`entry/src/main/ets/pages/Index.ets`（头部 + 「⋯」菜单（识别模式/设置）、转写区、录音按钮、声纹面板、设置面板）。
- 端侧：`entry/src/main/ets/services/LocalEngine.ets`（授权 → prepareRuntime → 引擎；会话参数含 `enableVoiceprintVerification` 与 `enableSpeakerVad`）。
- 云端：`entry/src/main/ets/services/CloudService.ets`（声纹注册/查询/删除 + `/tuling/ast/v3` 流式识别）。
- 声纹录音：`entry/src/main/ets/services/VoiceprintSamples.ets`；设置：`common/AppPrefs.ets`；视觉 token：`common/Theme.ets`。
- 构建：`build.sh`（解析 sherpa 符号链接为真实路径、构建后恢复；产出未签名 HAP）。

## 云端协议（已用合成语音实测）

默认服务 `https://113.46.211.82`（设置里可改）。

- 注册：`POST /api/asr/enrollment`，multipart 字段 `audio_far`/`audio_mid`/`audio_near`（16 kHz 单声道 WAV），请求头 `X-Voiceprint-Key`（每台安装随机生成，界面不显示）；返回 `data.enrollmentId`。
- 状态：`GET /api/asr/enrollment/status`（同一请求头）→ `data.available / enrollmentId / reason`。
- 删除：`DELETE /api/asr/enrollment/{id}`。
- 识别：`wss://<host>/tuling/ast/v3`，首帧 `parameter.asr_config` 含 `enrollment_enable=true`、`enrollment_id`、`enable_speaker_vad=true`；音频帧 `header.status=1` + base64 PCM；结束帧 `status=2`。返回 `payload.result.msgtype`：`Progressive`（中间）/`sentence`（定稿，文本在 `ws[].cw[].w`）；他人语音返回空 `sentence`，`header.status=2` 或 `ls=true` 为结束。
- 113 的 Caddy **必须带 SNI**。curl/LibreSSL、Python、鸿蒙网络栈访问 IP 时都不发 SNI → 握手失败（鸿蒙报 `curl_code 35`）。本机验证用 pyOpenSSL 强制 SNI 的转发脚本（不入库）。

## 当前状态（2026-10-21）

- [x] 拉取 AmphionRuntime 最新 main（`b56b240d`），建分支 `feat/harmony-target-speaker-app`。
- [x] 工程骨架、主题、图标（SVG）、录音/播放工具（复用 Demo 的 worker 采集）。
- [x] 端侧服务：授权、运行时、引擎常驻、声纹注册/删除、目标说话人会话（Speaker VAD 默认开）。
- [x] 云端服务：注册/状态/删除、流式识别；协议用合成语音在本机实测通过（本人语音返回完整转写，他人语音返回空句；测试声纹已删除）。
- [x] 统一声纹注册：三段录音一键同时注册端侧与云端。
- [x] 一键同步增强：一端已有声纹时只补缺失的一端（按钮显示「同步到云端/同步到端侧」）；启动、端侧引擎就绪、切到云端时后台自动补同步（静默、60 秒节流）；在缺声纹的一端点「开始」会先自动同步再开始识别；重录任一段后按钮变为「用新录音更新声纹」，两端一起更新。
- [x] 界面：主界面以转写内容为主（按时间顺序、实时句在末尾并自动跟随）；头部只有品牌、声纹状态胶囊（未注册/已同步/待同步/同步中）、端云切换；声纹注册在底部面板；未注册时空状态给出「注册声纹」入口；设置面板（语种、称呼、服务地址）。
- [x] **去端云感知（10-21）**：删掉头部端云切换条与引擎状态行里的端/云字样，改为右上角「⋯」`bindMenu`（识别模式「标准/增强」+ 设置）；声纹面板去掉端侧/云端两块同步卡片，按钮统一为「注册声纹 / 用新录音更新声纹 / 完成声纹注册 / 重新注册声纹」；转写行去掉端/云标签和「匹配 X%」（只有端侧有相似度，会暴露引擎）；状态、底部提示、toast、服务层错误文案全部中性化（`CloudService`/`LocalEngine` 里也改了）；设置里「云端服务地址」改为「服务地址」，改地址后自动重新注册。
- [x] **真机交接问题（claude-b1 10-21）**：① 录音质量校验：20 ms 帧 RMS ≥ -40 dBFS 累计 ≥ 2 秒才保存（`VoiceprintSamples.voicedSeconds`），已存的旧录音也按此判定，不合格显示「没有录到清晰的说话声，请重录」；② 部分成功：一端成功即清 dirty，失败的一端清掉旧 id（云端另异步删旧注册，避免状态查询把旧声纹报成可用），按钮显示「完成声纹注册」；③ 云端失败日志：`readableError` 打出 BusinessError code/message（public），注册非 200 打出 http/code/message，用户提示附错误码；④ 声纹面板 `SheetSize.LARGE`。
- [x] **真机云端结论**：真机直连 `https://113.46.211.82` 实际可达（注册返回 HTTP 400 `too_short`：b1 留下的三段录音是底噪，0 s 有效语音），之前「云端失败」不是 SNI 问题。服务端拒绝原因已映射为中文提示。
- [x] 麦克风权限：录音前检查，拒绝后引导到系统设置；错误不再暴露原始 `system error`。
- [x] 共享模型补齐：`shared/models/asr/dingqiao/community-*` 从 COS 拉取并按 `community_diarization_1.json` 校验哈希，pooling 图本地派生（均被 .gitignore 忽略）。
- [x] sherpa native 库按仓库固定提交重编（`04_build_harmony_so.sh` 的 sherpa 部分），`05_package_har_libs.sh` 已打包。
- [x] 模拟器（Amphion_API24）验证：端侧授权 `LICENSED`、引擎就绪；扬声器外放合成语音录三段并注册端侧成功；识别本人 2 句（匹配 86%/77%）、过滤 3 段他人语音。
- [ ] **ONNX Runtime 补丁版**未完成：`build_harmony_onnxruntime.py` 需从 GitHub 拉 ORT 源码，经本机代理多次超时。当前 HAP 用上游预编译 ORT 1.16.3（功能正常；补丁只降低线程空转 CPU）。拉取在 `third_party/.derived/onnxruntime-ohos-1.16.3-*/source` 重试中，成功后重跑该脚本和 `05_package_har_libs.sh` 再重编 HAP。
- [ ] **真机签名**：本机唯一的 AGC 调试 profile 绑定旧包名、已于 2026-09-08 过期，且不含当前真机。需要用户在 DevEco Studio 登录华为账号，为 `com.amphion.voice` 自动生成调试签名（含已连接设备）。
- [ ] **真机授权**：拿到真机签名后，以 debug 版启动读取日志中的 ODID（不要外传），签发绑定该设备、仅 ASR、短期的内部授权放到 `entry/src/main/resources/rawfile/amphion-license.lic`（已被 .gitignore 忽略）。
- [ ] ~~云端 SNI~~：真机已确认可直连（见上），暂不需要改服务端；如别的设备复现握手失败再评估。
- [ ] 真机真人复测（当前装机版本 HAP sha256 前缀 `d9c7c7346df0`，10-21）：真人录三段 → 一键注册 → 「标准」「增强」各测本人、旁人、交替说话；确认两种模式下页面文案完全一致。
- [ ] 真机全流程验证：真人录三段 → 端云同步注册 → 端侧/云端各测本人、旁人、交替说话；记录过滤与漏字情况。
- [ ] 交付形态：确认最终包名、版本号、应用图标；正式签名与正式授权走 `delivery/ASR_DELIVERY_WORKFLOW.md` 与离线授权流程。
- [ ] 提交与 PR：用户确认后再提交（Conventional Commits，中文说明）。

## 已知限制 / 注意

- 模拟器 ODID 为空，只能用不绑设备的授权；本机为模拟器签了一份仅 `com.amphion.voice`、仅 ASR、2026-11-15 到期的内部授权（只在本地，不入库）。
- 合成语音外放测试只能证明链路与状态正确，不能证明真人声纹精度；第二句开头混入少量旁人语音，需真机真人复测。
- Hvigor 拒绝符号链接模块路径；`build.sh` 会临时改写 `build-profile.json5`，构建结束自动恢复，并还原 sherpa 派生目录里被 ohpm 改写的 lock 文件。
- 本机未安装独立 Command Line Tools；当前用 DevEco Studio 自带的 node/ohpm/hvigor/sdk（通过 `DEVECO_CLI_CLT_PATH` 指向映射目录）。仓库规范要求独立 CLT，正式构建前应补装。

## 变更记录

- 2026-10-21：建立工程与本文件；模拟器端侧链路跑通；主界面改为转写为主、声纹收进底部面板；声纹一键同步（补缺失端、后台自动补、开始前兜底）。模拟器截图在会话 scratchpad，未入库。
- 2026-10-21（claude-b0 接手）：按用户要求去掉页面上的端云感知，端云选择收进右上角「⋯」菜单（标准/增强）；声纹注册界面只显示一个声纹；处理 b1 交接的 5 个真机问题（录音质量校验、部分成功按钮、云端错误码日志、LARGE 面板）；真机确认云端可达，失败原因是底噪录音。已编译签名并装到测试真机。真机调试先关 hilog 流控：`hdc shell hilog -Q pidoff; hdc shell hilog -Q domainoff`。构建需 `DEVECO_CLI_CLT_PATH` 指向映射 DevEco 工具的目录（hvigor/ohpm/sdk/tool/node 软链到 `/Applications/DevEco-Studio.app/Contents/tools|sdk`）。
- 2026-10-21（claude-b1 误入期间的改动，未提交，claude-b0 已核对保留）：转写区改为 List + 常驻实时行、逐字平滑（`util/SmoothText.ets`）、中间结果稳定 0.8 秒才显示、同一分钟时间只显示一次、会话分隔线、「回到最新」、句尾播放（`util/SentenceClips.ets`，设置里可关；云端用 `audio_range`，端侧无偏移时用本地时钟截取，两种模式都可用）、已过滤段数按连续区间计数、调试版 `--ps replay` 回放（`util/DebugSession.ets`、`EntryAbility.ets`）。`Recognizer.onFinal` 增加 startSample/endSample。核对结果：去端云感知的改动未被覆盖，构建通过。
- [x] ~~待处理：云端他人语音的中间结果会泄漏~~ 已修（claude-b1，10-21，见下条变更记录）。原记录：（b1 在 113 实测）：他人（Meijia 音色）的 Progressive 会带出完整文本，最后才以空句撤回；端侧他人中间结果 0.3–0.7 秒内被拒识。现有「稳定 0.8 秒才显示」只能部分遮住，长句仍可能露出，且两种模式表现不一致。方向：增强模式下中间结果等服务端说话人判定后再显示，或服务端对未确认目标的 Progressive 不下发。
- 2026-10-21（claude-b1，用户确认 amphion-voice 由 b1 接手，b0 不再改）：
  - 增强模式门控：服务端只对已确认是本人的句子先发 `speech_started`（带 segId）；他人语音的 Progressive 没有对应的 `speech_started`。`CloudService` 只显示已确认 segId 的中间结果。抓包证据在 b1 会话 scratchpad（`cloudtest/raw-mixed.jsonl`），不入库。
  - 显示稳定窗口分两档：一句开头 1.2 s（端侧拒识他人最长约 1.1 s），已有文字后 0.6 s。中间结果末尾标点不显示（云端预览的句号来回跳）。
  - 说话中出现 ≥0.9 s 停顿后又有人开口（App 用音频电平判断），新出现的字最多缓 2.5 s 等定稿确认，防止端侧把紧跟的他人开头几个字并进本人句子、在屏幕上露出后再撤回。
  - 顶部去掉「已过滤 N 段他人语音」（用户要求），保留「N 句」。
  - 验收方法（仅调试版）：`hdc shell aa start -a EntryAbility -b com.amphion.voice --ps replay /data/storage/el2/base/haps/amphion_voice/files/debug/<wav> --ps engine local|cloud`，App 走与麦克风完全相同的链路回放，并在 `files/debug/timeline-*.json` 记录每帧显示内容；麦克风会话的原始输入保存在 `files/debug/session-*.wav`（保留最近 5 个）。分析脚本、回归音频（用户本人注册录音 + 合成他人语音，属个人数据）都只在 b1 会话 scratchpad，不入库。
- 2026-10-21 晚（claude-b1，按用户「中间结果先缓步返回、定稿再缓步替换，不要等太久」调整）：
  - 去掉 0.8/1.2 s 稳定窗口和停顿后缓冲；只在一句开头等 0.25 s（滤掉单个噪声）。首字延迟由约 1.2 s 降到约 0.26 s（回放实测）。
  - `SmoothText`：比较时忽略标点（定稿只是在原文里补标点，不重打）；有差异的尾巴逐步收回再逐步打出；中间结果暂时变短或回退超过 4 个字时视为不可靠预览，屏幕保持不动，等后续中间结果或定稿。
  - 增强模式：只显示服务端已发 `speech_started` 的 segId 的中间结果（他人中间结果不再显示）；中间结果末尾标点不显示。
  - 顶部去掉「已过滤 N 段他人语音」。
  - 回放回归（装机 HAP sha256 前缀 `d422c5affd87`）：增强·交替/本人、标准·交替/本人共 4 场定稿全对；增强两场屏幕上从未出现他人文字，回退 8–10 次，定稿替换 ≤0.19 s；标准·本人定稿替换 ≤14 ms。已知取舍：标准模式下他人紧接本人开口时，前几个字会短暂显示后撤回（定稿里没有）。「只有他人」两场被用户真机使用打断，未计入。
- 2026-10-21 晚（claude-b1）多人声纹管理：
  - `AppPrefs` 新增声纹列表 `VoiceprintProfile`（id、名字、云端 Key、端侧 id、云端 id），选中一个作为当前识别对象（两种引擎每次只能识别一个目标说话人）。原有 `localVoiceprintId/cloudEnrollmentId/profileKey/profileName` 改为作用于当前声纹，注册/同步/识别流程不变。
  - 升级迁移：旧的单个声纹自动变成列表里的「我」（id `legacy`），原 `voiceprint/*.wav` 移到 `voiceprint/legacy/`，端侧/云端注册保留，无需重录（真机已验证）。
  - 声纹面板：人员列表（单选切换当前识别对象、每行可删除）、「添加声纹」（输入名字后新建并切换过去，再录三段注册）、当前人员的录音与注册。删除会同时删端侧注册、云端注册（用该人的 Key）和录音。识别中、录音中、注册中禁止切换。顶部胶囊显示当前识别对象的名字。设置里「称呼」改为「当前声纹的名字」。
  - 修复：增强模式偶发「the first AST frame must have status=0」——WebSocket.send 是异步的，并发调用不保证按序发出；`CloudService.sendJson` 改为串行队列。
  - 调试工具修复：时间线清理按时间戳而不是文件名排序（原来总是先删掉 cloud 的记录）。

- 2026-10-21 夜（claude-74）吐字慢定位与转写呈现：
  - **定位（同一录音按实时速度直推 113，带/不带声纹对照；lag = 收到时刻 − 结果覆盖的音频末尾）**：不带声纹中间结果 lag 稳定 0.2–0.6 s、句末定稿 0.8–0.9 s；带声纹（`enrollment_enable`）一句之内 lag 随句长增长 0.44 → 1.86 s，中间结果间隔从 0.75 s 拉长到 2.4 s，句末定稿 1.2–1.9 s；多人混说时句子被拖长，定稿 2.7–3.5 s 后一次性到达。关掉 `enable_speaker_vad` 结果相同，**慢在服务端声纹核验（成本随句长增长），不在 App 或网络**。真机回放带声纹比不带声纹首字晚 0.9–1.1 s；另见服务端常在 `speech_started` 前约 0.7 s 已发出本人的 Progressive，App 门控会丢掉这段（为不露出旁人文字，暂保留门控）。
  - 端侧（标准）：最后一个中间结果后 2.3–2.6 s 才出定稿，因 `vadEnd=1600`；改为 800（与 SDK 会议 Demo 一致），回放定稿提前 1.0–1.5 s。取舍：句尾很轻的声音会单独成句（回放多出一句「我也不是。」），第 3 句前几个字识别有变化。
  - 呈现（`SmoothText` + `LiveItem`）：按服务端推送节奏匀速打字（每批字铺满到下一批预计到达前，定稿 0.25 s 内补完，排队的旧定稿 0.1 s）；修正在原位逐字改写，不再先删后打；新字浅灰，0.6 s 不变或来自定稿即转为正文墨色，转入历史记录时外观不变；旁人撤回淡出。回放对比：上屏更新间隔中位 34 ms（突发）→ 101 ms（匀速），回删 2 → 0 次。装机 HAP sha256 前缀 `f90bf8475e7b`。
  - [x] 服务端（2026-10-22 上公网，App 与协议不变）：每句先由目标说话人模型确认是本人，之后的中间结果改用普通模型；定稿仍走目标说话人模型。公网实测增强模式中间结果延迟中位 0.82 → 0.35 s，多人混说 0.85 → 0.32 s，23 s 长句不再越说越慢；定稿逐字不变，旁人整句不再出现在中间结果里。注册时长服务端同步限定 5–8 秒，与 App 一致。
  - [x] 服务端（2026-10-22，已进 main-td 与交付包，公网未换版）：连续说话到 20 s 上限时，原来整点硬切会丢字（实测丢「只有我」）；改为在上限前 3 s 内平均能量最低的 200 ms 换气处切开。23 s 长句一字不丢。模拟器 App 回放长句、本人、混说三条结果都正确，混说只出本人 3 句。
  - [ ] 模拟器经本机代理回放时，会话偶发被服务端以「音频队列满」（`pcm_queue_full`）断开，修复前后的版本都会出现，公网真机暂未出现。服务端只能缓冲约 2.5 s 音频，手机网络卡顿超过这个时间同样会断开，需另行评估。
