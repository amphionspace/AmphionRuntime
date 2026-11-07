# EC521S 锁屏发热复现：设备、客户基线与测试进展（2026-11-04）

> 归档说明（2026-11-07）：本文随 PR `perf/android-asr-idle-power` 进入主线。文中提到的 `asr/tools/device/run_thermal_ondevice.sh` 一并入库；第十三节的 demo 前台服务改动（`e0b5fe60`）仍只在分支 `docs/ec521s-lock-heat-20261104` 上，不在这个 PR 里。

状态：**ash 冻结已找到有效豁免**：设备「手机管家 → 应用启动管理」将 demo 设为手动管理 + 允许后台活动，物理拔线锁屏不再冻结（16.7）。`deviceidle` 白名单与 `dumpsys battery unplug` 模拟均已证伪（16.1、16.6）。**新问题**：不充电锁屏吞吐只有插线锁屏的约 1/6，原因未查。尚无有效的 60 分钟不充电数据。本文件用于让后续 agent 快速接手，记录已确认的事实、已排除的问题、当前测试状态与下一步。

## 一、问题与客户基线

客户反馈：记录仪、无角色分离，FGS 常驻，**不充电**，60 分钟（前 10 分钟亮屏非锁屏，后 50 分钟锁屏）。

| 指标 | 数值 |
|---|---|
| 背壳累计升温 | +12.5 ℃ |
| 背壳前 10 分钟 | +4.5 ℃ |
| 背壳前 30 分钟 | +10.8 ℃ |
| 前壳累计升温 | +11.5 ℃ |

曲线形态：前 30 分钟占大部分升温，之后趋缓，属于电池供电密闭外壳的常见饱和形态。该基线是**无角色分离**的，不含 Sortformer。

## 二、测试设备（已核实）

| 项 | 值 |
|---|---|
| 型号 | EC521S（TD-TECH，`com.tdtech.*` 系统应用） |
| SoC | MediaTek MT6853（天玑 720 级），**不是麒麟**，此前麒麟 NPU 的结论不能直接迁移 |
| 系统 | Android 10，SDK 29，3.5 GB RAM |
| CPU 簇 | policy0：cpu0–5，policy6：cpu6–7，峰值均 2.0 GHz |
| 锁屏后可用核 | `key-background` cpuset = cpu0–3 + cpu7 |
| 温度节点 | `shell_frame`=thermal_zone25，`shell_front`=zone26，`shell_back`=zone27，电池=zone24 |

## 三、代码侧已确认的事实

- `asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt` 约 640 行注释写明"保持 PCM 全量进 ASR"：所有音频（包括静音）都送入 encoder，VAD 只用于断句，不减少计算。
- `asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoEngineConfig.kt`：默认 `DEFAULT_ASR_NUM_THREADS = 4`。
- 角色分离（Sortformer）在 Android 侧仍全部是 CPU（sherpa 预编译 ORT 1.24.3）。`asr/android` 中没有 NNAPI 或厂商 NPU 代理代码。
- 声纹/角色分离配置由客户集成决定，本次 demo 测试未开角色分离。

## 四、demo 授权问题（已解决）

- 现象：`引擎初始化失败：1002200032 code=6006: INVALID`。
- 原因：`6006` 对应**许可已过期**（到期日加宽限期之后），不是设备白名单问题。Demo 许可脚本设计上不绑定设备 SN。
- 处理：用本地私钥重签 2 个月试用许可（脚本 `asr/tools/license/issue_dingqiao_demo.sh`），到期 2027-01-04，重新打包 APK 并安装，引擎初始化成功（界面显示"默认中英模型已就绪"）。
- 私钥位置：`.secure/amphion-license-private.pem`，权限 600，`.secure/` 被 `.gitignore` 忽略。原件已从 `~/Downloads` 移入。**不要把私钥内容打印、复制或提交。**
- 安装注意：每次 `adb install` 都需要在设备屏幕上手动确认，否则返回 `INSTALL_FAILED_ABORTED: User rejected permissions`。

## 五、测试方法与设备端脚本

测试 App：`com.amphion.dingqiao.demo`（0.3.9，debug APK，`--ez demoFileInput true` 为文件输入模式）。

**不是客户的记录仪 App**：没有前台服务，熄屏后可能被系统挂起。结论只能用于衡量 SDK 负载，不能直接等同客户整机表现。

输入音频：仓库 `.local-archive/accuracy/plain/` 的 120 条短语音（约 36 分钟）循环拼接成 3600 秒、16 kHz 单声道 16 bit。**单人片段，不代表真实会议，不用于评估角色分离。**

设备端脚本已入库：`asr/tools/device/run_thermal_ondevice.sh`。运行在设备本地，不依赖 adb：
1. 基线：每 60 秒记录一次温度与电池状态。只在 **USB 离线**（`/sys/class/power_supply/usb/online=0`）时累计稳定计数，连续 5 次 `shell_front` 变化 ≤ 0.3 ℃ 视为稳定，最长等待 3600 秒。
2. 启动：屏幕超时设为 30 分钟，`am start --ez demoFileInput true`，滑动 4 次露出按钮后点击 `(120,287)` 开始识别。
3. 测试：亮屏 600 秒后 `input keyevent 26` 熄屏，总时长 3720 秒。
4. 保护：`shell_front` 连续 3 次 ≥ 50 000 m℃ 则强制停止 demo 并记录 `guard_stop`。
5. 输出：`/sdcard/amphion_thermal/`，包括 `samples.csv`（温度、USB、电量、pid）、`top.txt`（每分钟每线程 CPU）、`status.txt`（阶段时间点与起始温度）、`logcat.txt`（demo 相关日志）、`DONE`。

启动命令（需要 adb，插线时执行）：
```
adb push asr/tools/device/run_thermal_ondevice.sh /data/local/tmp/run_thermal.sh
adb shell 'chmod 755 /data/local/tmp/run_thermal.sh; MODE=full INTERVAL=60 STAB_MAX=3600 setsid nohup sh /data/local/tmp/run_thermal.sh </dev/null >/dev/null 2>&1 &'
```

## 六、已验证的脚本行为

- `setsid nohup` 启动后，adb 会话结束脚本仍继续运行（已验证，干跑）。
- **拔线后脚本仍在运行**（已验证：拔线约 3 分钟后重新插线时，PID 仍存在，`samples.csv` 持续增长）。
- 早期版本的问题（已修复）：脚本曾因 `ps` 显示进程名为 `sh` 而误判未运行；`/proc/*/cmdline` 的 grep 会匹配自身，需要用 `run_therm[a]l` 之类的写法避免自我匹配。
- 早期版本的问题（已修复）：`svc power stayon` 只在充电时生效，改为 `settings put system screen_off_timeout`。
- 早期版本的问题（已修复）：基线稳定计数未区分充电状态，插线期间的平稳会被误计入。现在只在 USB 离线时计数。

## 七、当前状态（截至本文撰写）

- 脚本在设备上运行，PID 11367，处于**基线等待**阶段，**尚未开始 demo 测试**。
- 基线期间 USB 曾有两段离线（约第 664–785 秒离线），随后又插回线，稳定计数被清零。
- 已采集的离线样本显示 `shell_front` 从 33632 降到 33198 m℃，即约 -0.4 ℃，说明插线充电期间的热量正在散掉，基线尚未平稳。
- 基线期间屏幕保持亮着，由系统超时决定，**锁屏动作只在 demo 开始后 600 秒执行**。
- 按脚本设计，最迟在脚本启动后 3600 秒内开始 demo 测试，之后再 3720 秒结束。

## 八、未解决的问题与下一步

1. **等待基线稳定并完成测试**：由设备端脚本自动执行。结束后接线，用 `adb pull /sdcard/amphion_thermal` 取回数据。
2. **与客户条件的差异**（需要在结论中说明）：
   - demo 没有前台服务，客户的记录仪有；
   - 基线阶段屏幕为亮屏，客户的"10 分钟非锁屏"是否也这样需要确认；
   - 音频为单人循环片段，不是真实会议；
   - 脚本未运行角色分离，客户的记录仪 App 是否开角色分离未知。
3. **对比方法**：用 `samples.csv` 中 `shell_back_m` 和 `shell_front_m` 相对基线起点的差值，与客户的 +12.5 ℃ / +11.5 ℃ 比较。注意 demo 与客户的 App 不同，差值只能说明 SDK 的增量负载，不能直接替代客户数字。
4. **若需要角色分离的增量**：需要单独做一组开角色分离的对照，本次不包含。
5. **Android NPU**：本次测试在 CPU 上运行，EC521S 的 MT6853 APU 与麒麟 NPU 无关，若要做 NPU 加速需要单独立项。

## 九、来源

- 设备数据：`adb shell` 读取的 `/proc/cpuinfo`、`/sys/devices/system/cpu/cpufreq`、`/dev/cpuset`、`/sys/class/thermal`、`dumpsys battery`、`dumpsys package`。
- 脚本：`asr/tools/device/run_thermal_ondevice.sh`。
- 授权：`asr/tools/license/issue_dingqiao_demo.sh`，错误码含义参见 `asr/android/docs/LICENSING.md` §授权校验。
- 设备端日志与样本：`/sdcard/amphion_thermal/`（设备上，未入库）。

## 十、第一轮结果：数据无效（2026-11-04 至 11-05）

设备端脚本完整执行（基线、亮屏 600 秒、熄屏、结束，`DONE` 存在），但**测试负载没有发生**，本轮数据不能用于结论。

### 10.1 demo 在启动约 9 秒后崩溃

- 启动 `12:59:23` 点击开始识别，`12:59:26` 冷启动完成，`12:59:32` 首个音频块进入 `SessionImpl.feedChunkAndDecode`（`SessionImpl.kt:747`）时抛出：
  `UnsatisfiedLinkError: No implementation found for float com.k2fsa.sherpa.onnx.OnlineRecognizer.getVadEndpointWaitSeconds(long, long, float)`
- 会话只处理了 `totalPcmBytes=177920`（约 5.5 秒音频）即结束。之后 60 分钟内没有识别、没有解码，属于空转。
- `samples.csv` 中 demo pid 始终存在，所以仅凭 pid 判断"在运行"是误判。

### 10.2 根因：APK 里的 sherpa JNI 库比 Kotlin 代码旧

- Kotlin 调用来自提交 `0b2893e4`（2026-09-22，`fix(asr): preserve pending speech at active VAD endpoints`），该提交已在 `main` 上。
- 设备上的 `libsherpa-onnx-jni.so` 来自本地构建目录 `asr/android/sdk/src/main/jniLibs/arm64-v8a/`（修改时间 2026-08-26），**不含** `getVadEndpointWaitSeconds` 符号（`strings` 计数为 0）。
- 该 `.so` 被 `asr/android/.gitignore` 忽略（`sdk/src/main/jniLibs/**/*.so`），不随仓库更新。源码中的 JNI 实现在 `third_party/.derived/sherpa-onnx-*/sherpa-onnx/jni/online-recognizer.cc`，说明源码是新的，二进制是旧的。
- 结论：这是**本地构建产物与源码不同步**的问题，并非 SDK 逻辑缺陷。但它会让 demo（以及任何用这份 jniLibs 打包的 APK）在 VAD 路径上直接崩溃，且 `NativeGuard` 只会记错误、不会让 demo 报告失败。
- 待确认：正式交付的 `.so` 是否由 CI 或 `asr/tools/04_build_android_so.sh` 重新生成。若是，则客户包不受影响，只影响本地 demo；若不是，则需要立即重新核对交付包。

### 10.3 其他观察（需要在重跑时处理）

- **锁屏阶段外壳温度读数全部为 0**：`shell_frame`、`shell_front`、`shell_back` 在 `locked` 阶段（44 行）全部为 0，只有电池温度（zone 24）有效。锁屏期间外壳传感器不可读，**客户的 +12.5 ℃ / +11.5 ℃ 对比在锁屏段无法直接用外壳温度复现**，需要改用电池温度或换采样方式，并在文档中说明。
- 亮屏 10 分钟（demo 已死）内，外壳温度从 `front 32.8 ℃ / back 39.7 ℃` 回落到 `31.98 ℃ / 38.41 ℃`，属于散热，不是负载升温，印证 10.2 的空转结论。
- 基线稳定判定在 USB 离线后约 40 分钟才完成（期间插线一次），起始温度 `front 32.8 ℃ / back 39.7 ℃`，记录于 `status.txt`。
- 设备 Wi-Fi/蓝牙/屏幕等其他后台负载未单独记录，需要在重跑时补充 `dumpsys` 基线。

### 10.4 重跑前置条件

1. 修复 jniLibs：用与 `0b2893e4` 之后源码一致的 sherpa 构建 `libsherpa-onnx-jni.so`，并确认 `strings` 能找到 `getVadEndpointWaitSeconds`。在重打 APK 前，先在本地跑一次 `asr/tools/04_build_android_so.sh` 或等价步骤，确认符号存在。
2. 重打 demo APK，安装前确认 `strings` 符号命中；安装后在 10 秒内检查 logcat 无 `UnsatisfiedLinkError`，并且 `totalPcmBytes` 随音频增长。
3. 锁屏段改用电池温度作为主指标，并在报告里注明外壳传感器锁屏不可读。
4. 重跑前明确"负载是否真实发生"的判据：logcat 中 `AmphionMetrics kind=SESSION` 的 `totalPcmBytes` 必须接近 `3600 × 16000 × 2`，否则本轮无效。

> 第十节的 jniLibs 问题已修复（见第十一节起），下述第十一至十三节记录修复后仍然无效的两轮，以及目前认为已解决的根因。

## 十一、jniLibs 修复后，第二轮：锁屏后零识别，根因是 demo 自身的 UI 线程喂音频

修复 jniLibs（`asr/tools/04_build_android_so.sh` + `05_package_aar_libs.sh` 重新编译 `libsherpa-onnx-jni.so`，确认 `getVadEndpointWaitSeconds` 符号存在）并重打 APK 后，功能验证通过（60 秒内完成 3 段识别，无 native 异常）。

随后完整跑完一轮不充电 60 分钟测试，`DONE` 正常，但 **44 条识别全部发生在锁屏前的 10 分钟亮屏窗口内，锁屏后 52 分钟零识别**。

排查定位到 `asr/android/samples/dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/MainActivity.kt` 的 `feedDemoFile`：原实现用 `window.decorView.postDelayed(this, 20L)` 驱动喂音频循环，**锁屏/窗口不可见后 `View.postDelayed` 的回调不再触发**，喂音频循环直接停摆。这是 demo 自身的 bug，与 SDK 无关。

修复：改成 `worker`（已有的单线程 executor）自驱动的 `while` 循环 + `Thread.sleep(20L)`，不依赖 `decorView`/窗口状态（已提交，见 `asr/android/samples/dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/MainActivity.kt` 的 `feedDemoFile`）。

同时发现**锁屏阶段外壳温度传感器读数为 0**（`shell_frame`/`shell_front`/`shell_back` 全部如此，电池温度正常），这个现象在后续每一轮锁屏测试里都稳定复现，原因未查（怀疑锁屏降频/降权后这几个 sysfs 节点本身不可读，而不是数值异常），后续分析一律改用电池温度或 `dumpsys thermalservice` 的 `SKIN_T` 作为锁屏段的温度口径。

## 十二、worker 线程修复后，充电验证通过，但不充电真机仍然零识别——根因是厂商 ash 休眠框架冻结了整个进程

**20 分钟充电验证**（`MODE=validate`，2 分钟亮屏 + 15 分钟锁屏）：锁屏后识别**确实持续**（14 条），证实 worker 线程修复本身有效。副作用：锁屏后解码耗时变成音频时长的 4.7～5.2 倍（例如 29.6 秒音频解码耗时 140 秒），这是锁屏后 cpuset 收紧到小核（`key-background` cpuset，见第二节）导致的算力不足，**不是新缺陷**，鸿蒙侧 `docs/speaker/SCREEN_LOCK_AND_PARTIAL_LAG_20261012.md` 记录过同类现象，这次在 Android/MT6853 上独立验证到。

**随后不充电正式跑一轮**：又是零识别。日志里找到真正的根因——设备上有一套厂商定制的后台应用休眠调度（logcat tag `PG_ash` / `ash_trans`，疑似 TD-TECH/华为系 ROM 的"App Standby Hibernation"）：

```
screen off trigger to nap: com.amphion.dingqiao.demo        # 锁屏后约 35 秒
transition to: doze
screen off app: com.amphion.dingqiao.demo goes to H
transition to: hibernation
perform H actions ...  P_service OK! P_job OK! P_BC OK! F_Z OK!   # 冻结服务/任务/广播
```

这套机制**只在不充电时触发**（充电验证全程 `PG_ash` 日志里没有任何冻结记录），和 cpuset 收紧是两件独立的事：cpuset 让已经在跑的线程变慢，ash 冻结是直接把整个进程（包括服务）暂停，零 CPU。之前第十一节"锁屏后零识别"的第一轮，很可能 UI 线程 bug 和 ash 冻结两个问题同时存在，当时只定位到了前者。

## 十三、加前台服务不够，真正生效的是 deviceidle 白名单

假设“客户 App 是前台服务（FGS），所以不受 ash 冻结”，于是给 demo 加了 `TranscriptionForegroundService`（`foregroundServiceType="microphone"`，持久通知），在 `startListening`/两条正常停止路径/`onDestroy` 挂了启停（已提交）。

**结果：FGS 不够。** 加完 FGS 后再跑一轮不充电 60 分钟测试，`PG_ash` 日志**仍然**打出完整的 `screen off trigger to nap → doze → hibernation → P_service OK!` 序列，52 分钟锁屏期零识别，和没加 FGS 时一样。说明这套厂商 ash 框架不认标准 Android FGS 契约的豁免，`P_service` 这一步把我们刚加的前台服务本身也暂停了。

用 `adb shell dumpsys battery unplug`（标准 Android 开发者命令，伪造"未充电"状态给 `BatteryManager`，**不改变 `/sys/class/power_supply/usb/online` 这个裸 sysfs 节点**，所以不能让 `run_thermal_ondevice.sh` 的基线等待误判，只用于手动单点诊断）在物理仍插线的情况下快速复现问题，逐个试豁免手段：

- `adb shell cmd deviceidle whitelist +com.amphion.dingqiao.demo`（标准 Android 省电白名单）加入后，模拟不充电 + 锁屏 2 分 20 秒，logcat 里**完全没有**再出现 `screen off trigger to nap`，期间识别持续产出（index 1、2 两条，解码仍慢，符合第十二节的 cpuset 结论，不是新问题）。

> **更正（2026-11-06，第十六节）：下面这条结论已被第五轮真实拔线测试推翻，`deviceidle` 白名单挡不住 ash 冻结。保留原文仅作记录。**

**结论（已推翻）：`cmd deviceidle whitelist +pkg` 是目前确认有效的豁免手段**，已经写进 `asr/tools/device/run_thermal_ondevice.sh`（脚本启动时自动执行 `cmd deviceidle whitelist +$PKG`）。FGS 代码保留（于客户场景身份对齐、无害），但不依赖它生效。

**对客户场景的推论（未验证，需标注为推测）**：客户的记录仪 App 能在锁屏下持续工作，很可能是因为它已经被厂商自己的 MDM/企业预置流程（设备上装有 `com.tdtech.mdm_service`）加入了这套白名单或等价的"受保护应用"配置，而不是单纯因为它是 FGS。这意味着**客户报告的 +12.5℃/+11.5℃ 基线，大概率反映的是真实持续解码的负载**，不是被冻结后的假象——但这是推论，没有拿到客户 App 本身在这台机型上的白名单状态核实。

## 十四、下一步

1. **用修复后的脚本重新跑一轮真实的不充电 60 分钟测试**（物理拔线，不用 `dumpsys battery unplug` 这个诊断用的模拟手段）。判据同第十节：`totalPcmBytes`/识别条数在锁屏后必须持续增长，且 logcat 不出现 `screen off trigger to nap`。
2. 这一轮如果有效，**改用电池温度或处理到的音频总量对齐发热曲线**，不用墙钟时间，因为锁屏后吞吐只有实时的 1/5 左右（第十二节）。
3. 如果需要确认客户 App 是否也在类似白名单里，需要客户侧配合核实（`adb shell dumpsys deviceidle whitelist | grep <客户包名>`），而不是在 demo 上继续推测。
4. 外壳温度传感器锁屏不可读的原因仍未查明（第十一节），如果后续要精确到"壳温"而非"电池温度"，需要单独定位。

## 十五、当前进行中（2026-11-05，截至本节写入时）

第十四节第 1 项已经在跑，**本节写入时尚未结束，还没有可用结论**。

- 已确认设备在启动脚本时成功写入 `cmd deviceidle whitelist +com.amphion.dingqiao.demo`（`adb shell dumpsys deviceidle whitelist` 核对过 `user,com.amphion.dingqiao.demo,10063` 在列）。
- 脚本以 `MODE=full INTERVAL=60 STAB_MAX=3600` 启动，设备侧 `start epoch=1793915023`（宿主机下发命令时刻，设备自身挂钟与宿主机不同步，换算方式见第十三节"查询设备自身挂钟"的 `adb shell date -d @<epoch>` 用法，连线后才能查）。
- 启动后用户已确认物理拔线，脚本随后会自行完成基线稳定等待（无 USB 供电、`shell_front` 连续 5 次温差 ≤0.3℃）、10 分钟亮屏、50 分钟锁屏、`force-stop` 收尾，全程不依赖 adb 连接。
- **接手者下一步**：设备插回 USB 后，先 `adb shell cat /sdcard/amphion_thermal/status.txt` 看 `DONE` 是否存在；再按第十节"判据"核对 `totalPcmBytes`/识别条数、`PG_ash` 日志里是否仍有 `screen off trigger to nap`（不应该再出现）。拉取产物用 `adb pull /sdcard/amphion_thermal/.`，分析方法与前几轮一致（本文第十、十一、十二、十三节各有一轮完整示例）。
- 这一轮如果验证通过（锁屏后识别持续、无 ash 冻结日志），就是本次调查第一份有效的 60 分钟不充电数据，可以据此和客户的 +12.5℃/+11.5℃ 基线做比较；如果仍然无效，需要先看是哪一类问题复发（第十、十一、十二、十三节分别是四类不同根因），不要假设是同一个问题。

## 十六、第五轮结果：deviceidle 白名单在真实拔线下无效，ash 仍冻结进程（2026-11-06）

第十五节那一轮已取回，**锁屏段无效**。现场备份在宿主机会话临时目录 `scratchpad/run5/`（`samples.csv`、`top.txt`、`status.txt`、`logcat.txt`、插线后 `logcat -b all`、`dumpsys deviceidle`），未入库。

### 16.1 时间线（设备时间 CST）

| 时刻 | 事件 |
|---|---|
| 06:44:33 | 基线稳定，`start_temp shell_front=29.41 ℃ / shell_back=34.98 ℃`，点击开始识别 |
| 06:44:42–06:54:34 | 亮屏 10 分钟，产出 utterance 1–44，`rtf≈1.03`（文件按实时节奏喂入） |
| 06:54:38 | 熄屏 |
| 06:54:39 | `PG_ash: screen off trigger to nap: com.amphion.dingqiao.demo`（熄屏后 **1 秒**） |
| 06:54:47 | `transition to: doze reason:app_type_unknown`，`P_GPS` |
| 06:55:01 | `transition to: hibernation`，`P_service OK / P_job OK / P_BC OK / F_Z OK`，进程冻结 |
| 06:55–07:16 | 零识别，`H_B interval 300000` 周期心跳 |
| 07:16:50 | 插回 USB，`unF_Z ... stop_ash`，`hibernation duration=1309316 ms`（≈21.8 分钟） |
| 07:16:51 | utterance 45 立刻产出，`decodeDurationMs=1337395`——冻结期间被挂起的那一句 |

冻结期间 `dumpsys deviceidle whitelist` 中 `user,com.amphion.dingqiao.demo,10063` **一直在列**，FGS 也在。即：**标准 deviceidle 白名单 + microphone FGS 都挡不住**。

宿主是 `com.huawei.iaware`（pid 2266，logcat tag `PG_ash`/`ash_trans`/`AwarePg`/`PGManagerService`），即华为 iAware/PowerGenie 的后台冻结，TD-TECH ROM 沿用。日志里 `reason:app_type_unknown` 和 `ignore front app ... is front app` 之后依然进入 hibernation，说明它按自己的应用分类/受保护名单决策，与 AOSP deviceidle 无关。

### 16.2 第十三节为什么得出错误结论

第十三节的验证用的是 `dumpsys battery unplug`（物理仍插线）。iAware 的 ash 判定很可能读的是真实供电状态而不是 `BatteryManager` 的伪造值，所以那次"白名单后不再出现 nap"实际上是**ash 根本没进入未充电模式**，并不能证明白名单有效。这是验证手段本身的缺陷：**`dumpsys battery unplug` 不能用来验证 iAware/ash 相关行为**，以后诊断必须物理拔线。（该解释是推断：第十三节当时没有留下"未加白名单 + `dumpsys battery unplug`"下 ash 确实触发的对照记录。）

### 16.3 可用的部分数据：亮屏 10 分钟段（负载真实发生）

| 指标 | 起点 | 10 分钟末（06:54:39） | 增量 | 客户基线 |
|---|---|---|---|---|
| `shell_back` | 34.98 ℃ | 37.91 ℃ | **+2.9 ℃** | 背壳前 10 分钟 +4.5 ℃ |
| `shell_front` | 29.41 ℃ | 35.67 ℃ | **+6.3 ℃** | 未给出前 10 分钟 |
| 电池 | 30.3 ℃ | 33.9 ℃ | +3.6 ℃ | — |

限制：demo 不是客户 App，单人循环音频，不开角色分离，亮屏 UI 负载与客户也不同；单轮，无重复。只说明"SDK 在亮屏、实时喂入下 10 分钟背壳 +2.9 ℃"这一个点。锁屏 50 分钟段仍无数据，客户 +12.5 ℃ 的主要部分（前 30 分钟 +10.8 ℃）无法比较。

### 16.4 下一步（需要决策，不要直接重跑 60 分钟）

重跑之前必须先找到在**物理拔线 + 锁屏**下真正有效的豁免，并用**短时（锁屏 3 分钟内即可，ash 熄屏 1 秒就触发）物理拔线**验证，不再用 `dumpsys battery unplug`。候选：

1. 设备上「手机管家 / 应用启动管理」把 demo 改为**手动管理并允许后台活动**（`com.huawei.systemmanager`，华为系 ROM 的受保护应用入口，iAware 读的大概率是这个）。需要在设备屏幕上手动操作。
2. 若 1 无效：核实客户记录仪 App 在该机型上是如何豁免的（MDM `com.tdtech.mdm_service` 下发的保活名单、或 TD-TECH 预置白名单），请客户侧提供 `dumpsys` 或配置，而不是继续在 demo 上猜。
3. 验证判据不变：熄屏后 logcat 不出现 `screen off trigger to nap: com.amphion.dingqiao.demo`，锁屏期间 `kind=UTTERANCE` 持续产出。

`asr/tools/device/run_thermal_ondevice.sh` 第 10 行的 `cmd deviceidle whitelist +$PKG` 保留（无害），但不能再视为豁免手段。

### 16.5 已执行：系统管理器豁免设置 + 插线流程检查（2026-11-06）

- 设备上「手机管家 → 应用启动管理」（`com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity`，adb 可直接 `am start`；`appcontrol.activity.StartupAppControlActivity` 需要华为签名权限，adb 拉不起来）中，「鼎桥语音识别 Demo」已改为**手动管理 + 允许后台活动**（未开自启动、关联启动）。
- **插线**短测（`MODE=validate LOCK_AFTER=60 TOTAL_S=300 INTERVAL=20`）：流程正常，无 native 异常；锁屏后仍有识别产出（utterance 4：59.0 秒音频解码 184 秒，符合第十二节的锁屏小核降速），logcat 无 `screen off trigger to nap`。
- **这只证明流程跑通，不证明豁免有效**：插线时 ash 本来就不冻结（第十二节充电验证）。豁免是否有效仍需物理拔线，或先证明 `dumpsys battery unplug` 能触发 ash（需要一组"自动管理 + 模拟不充电"的对照，16.2 指出第十三节缺这组对照）。

### 16.6 对照结论：`dumpsys battery unplug` 不能触发 ash，模拟断充电无效（2026-11-06）

补做了第十三节缺的对照：demo 改回**自动管理**（无系统管理器豁免），插线执行 `dumpsys battery unplug`（`USB powered: false` 已确认），`MODE=validate LOCK_AFTER=40 TOTAL_S=180`。

- 熄屏时 `PG_ash` 打出 `not only power charing.`，**没有** `screen off trigger to nap`，锁屏后识别继续产出（utterance 3：30.8 秒音频解码 48.6 秒）。
- 即：iAware/ash 读的是真实供电状态，伪造的 `BatteryManager` 状态骗不过它。第十三节"白名单后不再 nap"是这个假象，16.2 的推断由此坐实。
- **结论：任何 ash 相关验证只能物理拔线。** 现场备份：会话临时目录 `scratchpad/ctrlA/`。
- 对照结束后已 `dumpsys battery reset`，demo 已恢复为手动管理 + 允许后台活动。设备端已布置 `wait_unplug.sh`（等 `usb/online=0` 后自动跑 `MODE=validate LOCK_AFTER=60 TOTAL_S=300 INTERVAL=20`），只差物理拔线。

### 16.7 物理拔线短测：系统管理器「手动管理 + 允许后台活动」能阻止 ash 冻结（2026-11-06）

设置同 16.5，物理拔线，`wait_unplug.sh` 检测 `usb/online=0` 后自动跑 `MODE=validate LOCK_AFTER=60 TOTAL_S=300 INTERVAL=20`。全程 `usb_online=0`。现场备份：会话临时目录 `scratchpad/unplugB/`。

**冻结：已阻止。** 熄屏后 ash 仍会评估（`screen off trigger to nap` → `delay to nap: 3000`），但随后是：

```
PG_ash: not unify HB of pkg by user: com.amphion.dingqiao.demo
PG_ash: front app: com.amphion.dingqiao.demo goes to D
```

没有再进 hibernation，也**没有** `P_service / P_job / P_BC / F_Z`。约每 15 分钟重复一次 "goes to D"，始终不进 H。同一时段未豁免的 `com.amphion.asr.sample`（0.3.4，另一个测试应用，处于后台）照常被 `F_Z` 冻结，作为同机对照。锁屏 4 分钟窗口内 demo 线程合计 CPU 约 86–207%（`top.txt`），与插线锁屏（16.6 对照 A，约 196–244%）同一量级。

**新发现：不充电锁屏下吞吐远低于插线锁屏，原因未查。** 脚本 `validate` 结束后不会停 demo（脚本只在 `full` 的 guard 才 force-stop），demo 在拔线锁屏状态下又持续跑了约 1.5 小时，直到插回 USB：

| 条件 | 例句 | 音频 | 解码耗时 | 倍数 |
|---|---|---|---|---|
| 插线锁屏（16.5） | utterance 4 | 59.0 s | 184 s | 3.1× |
| 拔线锁屏（本节） | utterance 4 | 59.0 s | 1052 s | 17.8× |
| 拔线锁屏（本节） | utterance 4–11 合计 | 约 179 s | 约 92 分钟墙钟 | 约 31× |

识别一直在产出，不是冻结，但慢了约 6 倍。CPU 频率只在插线时读过（policy0/6 均 2.0 GHz），拔线期间未采样，所以不能确定是 ash "D" 状态的限频/限核、厂商电池策略还是别的原因。`amphion-cold-load` 名下的高 CPU 线程是 ORT 线程池继承了冷加载线程名（`AmphionRuntime.kt` `loadColdModelsInParallel`），即实际解码算力，不是重复加载。

**对发热比较的影响**：若客户 App 在相同豁免下也是这个吞吐，锁屏段实际解码量远低于实时，客户 +12.5 ℃ 中锁屏段的贡献不能用"持续实时解码"解释；反过来若客户锁屏段真实时解码，则其豁免方式或负载与 demo 不同。两者都需要数据，不能推断。

**下一步**：
1. 给 `run_thermal_ondevice.sh` 每次采样加 `scaling_cur_freq`（policy0/policy6）和 demo 所在 cgroup/cpuset，确认拔线锁屏的降速来源。
2. 带上述采样跑 60 分钟不充电正式轮（豁免设置保持，物理拔线），判据：无 `F_Z`/hibernation，锁屏期识别持续；按处理音频量和电池温度对齐发热。
3. 测试前 force-stop `com.amphion.asr.sample` 等无关 Amphion 应用，避免额外负载。

## 十七、客户报告分析与发热主因：ORT 线程池空转约占一半 CPU（2026-11-06）

### 17.1 客户 EC521S 实测（鼎桥 11-04 报告，邮件 2026-11-06「安卓锁屏离线ASR一小时长时验证」附件，原件不入库）

- App `com.tdtech.tiassistant` 1.1.0.089 zbBwcDebug，飞行模式，外放朗读，216 字/分钟，61.9 分钟。
- 背壳 29.97→42.43 ℃（+12.5 ℃，前 30 分钟 +10.8 ℃），Thermal Status 全程 0（未限频），功耗约 1.06 W（263 mAh/h）。
- 进程 CPU 全程累计 187 分 44 秒 / 61.9 分钟墙钟，**平均约 300%**，采样点瞬时 153%–775%。
- 锁屏后进程在 `foreground` cpuset，`cpus=0-7` 满核，未降入 `key-background`；`kind=UTTERANCE` rtf≈0.99，解码全程跟上实时。客户 App 锁屏期间没有被 ash 冻结（豁免方式未知）。
- 结论：客户场景就是"SDK 持续实时解码 1 小时"，发热量由 SDK 的持续 CPU 负载决定。

### 17.2 本机复测：SDK 实时解码稳定占用约 2.5 核

demo（与客户相同 SDK 路径，`numThreads=4`），插线亮屏、文件按实时节奏喂入，`/proc/<pid>/task/*/stat` 60 秒差分（`CLK_TCK=100`，100% = 1 核），policy0/6 均 2.0 GHz：

| 线程 | CPU |
|---|---|
| `amphion-cold-lo*`（9 个 ORT 线程池 worker，继承冷加载线程名） | 196.9% |
| `asr-decode-1`（ORT 调用方线程） | 61.0% |
| 后处理 / 回调 / UI / 其他 | 约 9% |
| **合计** | **266.6%** |

与客户的平均 300%（SDK 约 2.6 核 + App 自身）吻合。

### 17.3 simpleperf：一半以上 CPU 在 ORT worker 空转循环

`run-as … simpleperf record -e cpu-clock -f 1000 --duration 20`，49 410 样本（约 247% CPU）：

- 89.4% 在 `libonnxruntime.so`（sherpa 预编译 ORT 1.24.3，已 strip）。
- **51.2% 落在 `0x14b2c00–0x14b3000` 一段**。反汇编为纯标量的 load/compare/branch：读取取消标志（`ldarb`+`tbnz`）、按 `& 0x3ff`（1024 槽 RunQueue）轮询队列槽状态、对状态 3/2 做 CAS，没有任何 SIMD 指令。这就是 ORT `ThreadPoolTempl::WorkerLoop` 的 spin-wait。另有 7.4% 在 `pthread_rwlock_unlock`。
- 真正的 int8 GEMM（如 `0x147f5xx`，`eor 0x80`+`zip1` 的 QGEMM 打包）等其他 ORT 代码合计约 27.5%。
- 按 247% 折算，**约 1.3 核在空转**，有效推理约 0.7–1.0 核。

根因（代码层面）：`third_party/.derived/sherpa-onnx-*/sherpa-onnx/csrc/session.cc` 的 `GetSessionOptionsImpl` 只在 `__OHOS__` 下调用 `ConfigureHarmonyScheduling`（设置 `session.force_spinning_stop=1`，可选 `session.intra_op.allow_spinning=0`）。**Android 侧没有任何 spinning 配置**，ORT 默认 intra-op 空转开启。流式 ASR 每个 chunk 只做一次很短的 `Run`，worker 在两次 `Run` 之间持续空转。多个 session 各自带 `numThreads=4` 的线程池，于是出现了 9 个空转 worker。

### 17.4 状态

- 以上是测量和代码证据，**因果尚未用 A/B 证实**：需要在 Android 上关闭 spinning，重测 CPU、rtf 和延迟。
- 若 A/B 证实，这就是客户 +12.5 ℃ 中 SDK 可消除的主要部分，属于 SDK 缺陷，修复需走正常 PR、平台构建和真机门禁。

### 17.5 A/B 证实：关闭 ORT 空转使 SDK CPU 降 21–30%，识别实时性不变（2026-11-06）

方法：只在本地隔离 sherpa 源码（`third_party/.derived/…/session.cc`）里临时加 Android 实验开关，读取系统属性 `debug.amphion.ort_spin`：`stop` 设置 `session.force_spinning_stop=1`（与鸿蒙 `ConfigureHarmonyScheduling` 的默认值一致）；`0` 再加上 `intra_op/inter_op.allow_spinning=0`；未设置时行为与原版一致。这份改动**未提交**，实验后已恢复源码与 jniLibs，并核对 `getVadEndpointWaitSeconds` 仍在。

每种模式都冷启动 demo，从头喂同一段音频，预热 40 秒后测 60 秒；插线、亮屏、`vip` cpuset。两轮独立重复：

| 模式 | 进程 CPU（第 1 / 2 轮） | ORT worker | 调用方线程 | policy0 平均频率 | policy0 处于 2.0 GHz 的时间 | 8 核 busy 合计 |
|---|---|---|---|---|---|---|
| 默认（空转开） | 273% / 277% | 202–205% | 62% | 1200 MHz | 18.8 s / 60 s | 295% |
| `stop` | 191% / 205% | 119–130% | 63–66% | 999 MHz | 2.5 s | 229% |
| `0`（空转关） | 220% / 219% | 127–128% | 80% | 710 MHz | 0 | 238% |

- 每种模式 5 句识别的 rtf、首字延迟（`firstPartialLatencyMs`）、endpoint→final 延迟都在噪声范围内（例如 utterance 4 的首字延迟为 776 / 717 / 785 ms）。没有观察到实时性代价。
- `stop` 的进程 CPU 最低。`0` 把小核频率压得最低（不再出现 2.0 GHz），但调用方线程上升到 80%，推测是 worker 改为阻塞唤醒后，调度开销转移到了调用方。两者都明显优于默认。
- 大核簇（policy6）在三种模式下都主要停在 1836 MHz / 725 MHz，平均频率基本不变。剩下约 2 核是真实推理负载加调用方开销。
- 测试设备上的 demo 现在是这份实验构建（`debug.amphion.ort_spin` 未设置时行为与原版一致，属性已清空）。后续如果要做"开/关空转"的 60 分钟发热对照，可以直接复用，**不需要重新构建**；除此之外如需用到这台设备上的有效证据，必须先重装正式构建。

### 17.6 结论与边界

1. **客户 +12.5 ℃ 的直接原因**：SDK 在 EC521S 上持续实时解码，整个进程长期占用约 2.5–3 核（客户实测平均 300%），且一直满频率运行，散热又弱的封闭外壳就逐渐饱和升温。客户 App 锁屏不降组、不降频（Thermal 0），所以锁屏后负载不会下降。
2. **SDK 可消除的部分**：其中约 0.7 核（占进程 CPU 的 21–30%）是 ORT 线程池在两次推理之间的空转，Android 侧没有配置任何 spinning 选项（鸿蒙侧有）。这是 SDK 缺陷，修复方向明确：在 Android 的 `GetSessionOptionsImpl` 中对齐鸿蒙，设置 `session.force_spinning_stop=1`。
3. **还不能下的结论**：降多少 ℃ 没有测，CPU 和频率下降不能直接换算成温升。需要用同一 APK 在拔线条件下做 60 分钟开/关对照（豁免设置见 16.7，注意 16.7 中锁屏吞吐异常的问题）。另外，`numThreads=4` 是否过多（多个 session 各带 3 个 worker）尚未测试，可能还有进一步的空间。
4. **修复要求**：走正常 PR，在 `third_party/patches/sherpa-amphion` 增加补丁并补回归测试；Android 双平台构建，并完成真机识别精度和延迟门禁。本节的实验构建不能当作交付证据。

### 17.7 插线发热 ABA 对照：INCONCLUSIVE（2026-11-06）

在电池已充满（100%，电池电流在 ±5 mA 内）、亮屏且最低亮度的条件下，按"默认 → `stop` → 默认"各跑 30 分钟。**结果无效**：

- 冷却阶段的判据是每分钟变化不超过 0.2 ℃。这个判据在设备仍然很热时就会满足，三段的背壳起点分别是 33.6 / 41.0 / 43.2 ℃，后两段的温升被饱和效应压低了。
- 根本原因：**长时间插线时，背壳传感器（zone27）附近有一个与 SDK 无关的热源**。demo 停止、整机 CPU 约 2% 时，背壳仍有 46 ℃ 而且还在升；同一时刻系统报告的 `SKIN_T` 只有 26 ℃。推测是充电或供电电路。所以**插线状态下不能用背壳温升比较 A/B**。
- 只有第一段（起点干净）有参考价值：默认模式插线亮屏 30 分钟，背壳 +7.5 ℃，前壳 +10.1 ℃。这个数字不能和客户的拔线锁屏数据直接比较。

### 17.8 插线功耗 ABABAB 对照：停止空转使整机功耗降约 0.13 W（2026-11-06）

指标：`/sys/class/power_supply/hwbatt/charge_current_now`（USB 输入电流，mA）× `charge_voltage_now`（mV）。核实过它随负载变化：识别时 65–650 mA 跳动，空闲约 50 mA。电池充满时电池电流约为 0，所以这个乘积就是**整机全部电功率**，不受上述背壳热源影响。每段冷启动 demo，预热 40 秒后以 0.2 秒间隔采样 150 秒（约 390 点）；两种模式交替 3 轮，用来抵消漂移。每段识别句数都是 7。

| 段 | 模式 | 平均功率 | 进程 CPU |
|---|---|---|---|
| 空闲（前/后） | — | 0.248 / 0.257 W | 0 |
| 1 / 3 / 5 | 默认 | 1.489 / 1.442 / 1.387 W | 279 / 328 / 327% |
| 2 / 4 / 6 | `stop` | 1.359 / 1.296 / 1.286 W | 192 / 215 / 218% |

- 三组成对差值分别为 0.130 / 0.146 / 0.101 W，方向全部一致。均值**降低 0.125 W**，占 SDK 增量功耗（1.19 W）的 **11%**，占整机的 9%。
- **CPU 时间降了约 30%，功耗只降了约 11%**：被去掉的空转多数发生在小核，单位时间耗电低；功耗的大头是大核上的真实推理。
- 粗略估算（**推算，未实测**）：客户实测 1.06 W 对应 +12.5 ℃，约 12 ℃/W；去掉 0.13 W 约能少升 1–1.5 ℃。

### 17.9 修正后的结论

1. ORT 空转是真实存在的 SDK 缺陷，修复后约省 11% 的 SDK 功耗、30% 的 CPU 时间，实时性不变，应该修。但**它不是客户 +12.5 ℃ 的主因**。
2. 主因是真实推理负载：EC521S 上 SDK 实时识别约 1.0–1.2 W，在客户的封闭外壳里就对应十几度的温升。要明显降温，需要降低真实计算量。候选方向（均未测）：
   - `numThreads=4` 改为 2，减少大核高频驻留；
   - 静音段不送 encoder（目前全部 PCM 都送）；
   - 加大 chunk、降低解码频率；
   - 更小的模型。
   其中线程数可以沿用 17.5 的系统属性开关方式，用同一套功耗 ABAB 方法测量，成本最低。
3. 方法结论：在这台设备上，插线时可以用 USB 输入功率做 A/B，**不要用背壳温度**。

### 17.10 线程数 × 空转 2×2 功耗对照：两项合计降约 0.23 W（2026-11-07）

**方法**：与 17.8 相同（插线、电池满、最低亮度、USB 输入功率，每段 150 秒、约 400 点）。实验版 `libsherpa-onnx-jni.so` 读取两个系统属性：`debug.amphion.ort_threads` 只覆盖请求线程数为 4 的 ASR session（VAD、标点等 1 线程 session 不受影响）；`debug.amphion.ort_spin` 同 17.5。日志 `AmphionOrtSpin` 逐段核实生效。4 种配置各 3 段，按 `4 2 4s 2s | 2s 4s 2 4 | 4 2 4s 2s` 平衡排序，以抵消漂移。实验代码未提交，已还原。

| 配置 | 三段功率 (W) | 均值 | 相对默认 | 进程 CPU |
|---|---|---|---|---|
| 空闲（前/后） | 0.228 / 0.250 | 0.239 | — | 0 |
| 4 线程 + 空转（现状） | 1.381 / 1.518 / 1.510 | **1.470** | — | 256–275% |
| 2 线程 + 空转 | 1.327 / 1.341 / 1.360 | 1.343 | −0.127 | 146–152% |
| 4 线程 + 停止空转 | 1.320 / 1.289 / 1.344 | 1.318 | −0.152 | 177–187% |
| 2 线程 + 停止空转 | 1.261 / 1.228 / 1.239 | **1.243** | **−0.227** | 125–128% |

- 2 线程 + 停止空转的三段，都低于任何一段 4 线程 + 空转（最大 1.261 W，后者最小 1.381 W）。SDK 增量功耗从 1.23 W 降到 1.00 W，**降低 18%**；进程 CPU 从约 2.7 核降到 1.3 核。
- 两项不能简单相加：线程减到 2 后，空转本身也变少了，所以叠加的收益小于 0.127 + 0.152。
- **实时性无变化**：12 段都识别出 7 句。各配置的首个 partial 中位数都在 1.65–1.93 s，endpoint→final 中位数在 6.3–6.7 s，rtf 中位数 1.038–1.042（文件输入按实时速度送入），差异都在段间波动范围内。
- **未验证**：2 线程下的识别文本精度没有逐句比较；拔线锁屏（客户场景）下的温升也没有实测。
- 粗略估算（**推算，未实测**）：按约 12 ℃/W 计算，0.23 W 约对应少升 2.5–3 ℃。客户 +12.5 ℃ 预计降到约 +9.5–10 ℃。

### 17.11 最终结论

1. 客户 EC521S 温升的主因，是 SDK 实时识别的真实计算功耗，约 1.0–1.2 W。ORT 空转和 4 线程配置是可以低成本去掉的额外开销，合计约 0.23 W（SDK 增量的 18%）。
2. 建议的低成本修复：Android 端对 ASR session 设置 `session.force_spinning_stop=1`（与 Harmony 已有逻辑一致），同时把鼎桥默认 `DEFAULT_ASR_NUM_THREADS` 从 4 改为 2。两项在本机都没有实时性代价，正式合入前仍需按验证矩阵做精度回归和真机门禁。
3. 只靠这两项不能把温升降到"不明显"。要进一步降温，需要减少真实计算量：静音段不送 encoder、加大 chunk、换更小的模型。这些都会影响识别延迟或精度，需要单独评估。

### 17.12 熄屏吞吐：2 线程与 4 线程相同（2026-11-07）

**目的**：熄屏后进程进入 `/background` cpuset。需要确认减到 2 线程不会让熄屏吞吐更差。

**方法**：仍用 17.10 的实验版，插线，两种配置都停止空转，按 `4 2 2 4` 排序。每段亮屏启动、冷加载完成后熄屏 180 秒。看第 3 句（熄屏期间解码完成的那句）的音频时长与解码耗时之比。每段开始时 `mWakefulness=Asleep`、cpuset 为 `/background`，12 次采样都没变。

| 段 | 线程 | 第 3 句音频 | 解码耗时 | 吞吐 | 进程 CPU |
|---|---|---|---|---|---|
| 1 | 4 | 34.5 s | 98.8 s | 0.350× | 191% |
| 2 | 2 | 27.3 s | 76.7 s | 0.356× | 153% |
| 3 | 2 | 27.0 s | 76.8 s | 0.352× | 153% |
| 4 | 4 | 34.2 s | 98.1 s | 0.348× | 192% |

- 熄屏吞吐与线程数无关（0.348–0.356×），2 线程的 CPU 少 20%。熄屏下的瓶颈不在 ORT intra-op 线程数，所以减线程没有代价。
- 熄屏后两种配置都只有约 0.35× 实时，前两句（亮屏期间）rtf 约 1.06。原因是 demo 熄屏后被放进了 `/background` cpuset。客户 App 熄屏后仍在 `foreground` cpuset，满核运行，rtf≈0.99（17.1）。所以**客户场景对应的是 17.10 的亮屏满核对照**，本节只用来排除"减线程会让受限 cpuset 更慢"这一风险。demo 熄屏落后是测试载体的既有限制，与本次改动无关。

### 17.13 修复 PR 与验证范围

修复分两个提交：sherpa 补丁 `0038`（Android 所有 ORT session 设 `session.force_spinning_stop=1`）和鼎桥默认 `numThreads` 4 → 2。鸿蒙默认仍为 4。实测依据是 17.8、17.10、17.12，均来自读系统属性的实验库。正式构建的验证结果写在 PR 描述里。

**正式构建验证（2026-11-07，EC521S，PR 分支构建的 demo `e109db48…`，`libsherpa-onnx-jni.so` `f422f718…`）**：

| 检查 | 结果 |
|---|---|
| 功耗复测（同 17.8 方法，3 段） | 进程 CPU 123–125%，与实验版"2 线程 + 停止空转"（125–128%）一致；7 句全识别；首个 partial 中位数 1.66–1.89 s。整机 1.14–1.18 W。这轮空闲功耗是 0.26–0.28 W，和 17.10 不是同一轮，不比较绝对值 |
| `DqSdkCornerCaseTest` + `DingqiaoFinishFlushRegressionTest` + 语料 + 首字时延，共 33 项 | 32 项通过。`a13_userSequenceStress` 300 轮通过 |
| 失败项 `a01_tailFrame_abruptFinish_keepsTail` | 只在 `c_demo_4.wav` 上失败：立即 finish 丢了句尾一个字。这个文件是从 demo 输入里按 55 s 硬切出来的，结尾落在一句话中间。**main 等价构建（旧 native、4 线程）同样失败，丢的是同一个字**，所以是既有问题，不是本 PR 引入的；记为后续跟踪项 |
| 识别文本，9 个文件、1228 字 | 4 线程连跑两次逐字相同；main 与 PR 的 4 线程逐字相同，即停止空转不改变数值。2 线程与 4 线程有 4 处差异：3 处 2 线程更合理（"沿路商铺""拿给我""办案"），1 处只差一个逗号。线程数改变了浮点累加顺序；在这批小样本上看不出精度退化。**这不是正式精度评测** |

语料是 2 个仓库 fixture 和从 demo 输入切出的 5 段 55 s 音频。音频与识别文本都不入库。
