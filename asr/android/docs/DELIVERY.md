# Amphion Android SDK 交付指南（给我们自己看）

适用 SDK 版本：0.2.0

> 本文是「我们怎么把 SDK 交付给业务方」的内部 SOP。业务方只需要看 [INTEGRATION.md](INTEGRATION.md) 和 [PRIVACY.md](PRIVACY.md)。

## 1. 交付物清单

每次交付给业务方的目录结构（建议命名 `amphion-runtime-android-<version>-<date>/`）：

```
amphion-runtime-android-0.2.0-2026-05-25/
├── amphion-runtime-0.2.0.aar          # 唯一二进制；包含全部模型 + so
├── amphion-runtime-0.2.0-sources.jar  # 源码（仅 Kotlin 公开 API；可选）
├── INTEGRATION.md                      # 给业务方看的集成指南
├── PRIVACY.md                          # 隐私合规说明
├── CHANGELOG.md                        # 版本变更
├── LICENSE                             # 我们的协议（Apache-2.0）
├── NOTICE                              # 第三方依赖声明
├── consumer-rules.pro                  # R8/混淆规则（业务方开混淆时需要 include）
├── checksum.txt                        # AAR / sources.jar 的 sha256
└── samples/
    └── MainActivity.kt                 # 200 行最小集成示例（来自 :samples:public-demo 模块）
```

> 交付边界（必须严格遵守）：对外只交付 `:sdk` AAR + `:samples:public-demo` 来源；`:samples:internal-eval` 是对内评测版（含 INTERNET / FileProvider / OkHttp / 上传链路），永远不进交付包。详细见 §10。

只交付上面这些；不要把 `tools/`, `third_party/`, `sherpa-onnx/`, `samples/internal-eval/` 之类的内部资产带过去。

> 商用授权补充：标准交付包不含 license。每个客户的 `.lic` 由我方用私钥单独签发（见 §11），经安全渠道单独发给该客户，由其放进自己 App 的 `assets/`（默认文件名 `amphion-license.lic`）。交付给客户的 AAR 必须是「武装构建」（gradle.properties 注入了 license 公钥，见 §3.6）；未武装的 AAR 不做授权校验，仅限内部 / 评测使用。私钥与签发出的 `.lic` 都不进库（`.gitignore` 已忽略）。

## 2. 体积 / 性能预算

业务方的 Android 包会增加：

| 项 | 增量 (~MB) |
| --- | --- |
| AAR 本身 | ~280 |
| 安装到 internal storage | ~270（首次启动时解包） |
| 运行时 native 内存（仅中英 ASR + VAD，无后处理） | ~55 |
| 运行时 native 内存（中英 + 标点 + ITN + VAD 全开） | ~150 |
| 运行时 native 内存（preload 中英 + 粤英 + 共享 punct/itn + VAD） | ~180 |

部署到 一台 Android 12 / HarmonyOS 4.3 设备 的真实表现（本仓库 sample 在 demo 机上实测）：

| 阶段 | 耗时 |
| --- | --- |
| 应用安装（adb install） | 30-60 s（解压 280 MB APK） |
| 首次启动 → preInstall 完成 | 5-30 s（解 onnx/fst 到 filesDir） |
| 首次启动 → preload 全部完成（含解包） | 4-6 s（cache 命中后） |
| 后续启动 → 模型加载就绪（无 preload） | 1-3 s |
| 切换语言（已 preload） | ≤ 100 ms |
| 单段语音 final 出来 | 端点 → ITN+标点 ≈ 50-150 ms |

## 3. 准备 AAR 的完整流程

### 3.1 一次性准备（每台开发机做一次）

```bash
# 1) NDK 工具链：见 asr/tools/ANDROID_TOOLCHAIN.md
# 2) Gradle wrapper：cd asr/android && bash init_gradle_wrapper.sh
# 3) 同步 sherpa-onnx submodule：git submodule update --init --recursive
```

### 3.2 编 native .so

```bash
bash asr/tools/04_build_android_so.sh arm64-v8a
bash asr/tools/05_package_aar_libs.sh
# 输出会落到：
#   asr/android/sdk/src/main/jniLibs/arm64-v8a/{libsherpa-onnx-jni.so,libonnxruntime.so}
```

### 3.3 准备模型文件

```bash
# 中英 / 粤英 ASR：放到 asr/tools/demo-model/zipformer_L_zh_en/ 与 zipformer_L_yue_en/
# （内部模型走 ssh / s3，外部 demo 用 00_fetch_demo_model.sh）

# 标点：自动下载 + 校验 sha256
bash asr/tools/00_push_punct_model.sh --no-push

# 中文 ITN：自动 pip install + 编译 fst
bash asr/tools/00_push_weitn_fsts.sh --no-push

# 把全部 5 类资产打进 sdk/src/main/assets/amphion-models/
bash asr/tools/08_pack_sdk_assets.sh
```

`08_pack_sdk_assets.sh` 会校验缺漏的资产并尝试自动拉取（标点 / VAD），全部就位后写一份 `manifest.json` 仅供运维核对（运行期不读）。

### 3.4 编 AAR

```bash
cd asr/android
./gradlew :sdk:assembleRelease
# AAR 落在：sdk/build/outputs/aar/sdk-release.aar  (~280 MB)

# 想要源码 jar，跑这条：
./gradlew :sdk:publishReleasePublicationToLocalFileRepoRepository
# 落在：sdk/build/maven-repo/com/amphion/amphion-runtime/0.2.0/
```

### 3.5 装 sample 自验

```bash
./gradlew :samples:public-demo:installDebug
adb shell am start -n com.amphion.asr.sample/.MainActivity
```

人工测试清单：

- [ ] 第一次启动 splash 完成，进入 MainActivity 看到「中英 / 粤英」切换条
- [ ] 中英朗读「两点五八万」→ final 显示「2.58万。」（含 ITN + 标点）
- [ ] 切到粤英，读一句普通话以外的粤语短语，能正常 partial / final
- [ ] 把 app 杀掉重启，模型不再重新解包（`<filesDir>/amphion-runtime/install.flag` 存在）
- [ ] adb shell pm clear 清掉应用数据，重启自动重新解包

> 注意：默认 gradle.properties 公钥为空 = SDK 未武装 license，上面的 sample 自验跑在 DEV_UNLICENSED 状态、不校验授权。武装构建的 license 回归见 §3.6。

### 3.6 武装 license 公钥（正式交付构建必做）

未武装的 AAR（gradle.properties 公钥为空）不会做任何授权校验，只能内部用。给客户的正式交付构建必须注入公钥：

```bash
# 1) 一次性生成密钥对（私钥严禁进库；公钥贴进 gradle.properties）
python tools/license/gen_keypair.py --out-private ~/secure/amphion-license-private.pem
#    把输出的公钥 base64 填到 asr/android/gradle.properties 的 AMPHION_LICENSE_PUBLIC_KEY

# 2) 重新编 AAR（此时 BuildConfig.LICENSE_PUBLIC_KEY_B64 已注入，SDK 进入武装态）
cd asr/android && ./gradlew :sdk:assembleRelease
```

武装构建自验（在 sample 放一份测试 .lic）：

```bash
# 用同一把私钥给 sample 的包名签一份测试 license
python tools/license/issue_license.py --private-key ~/secure/amphion-license-private.pem \
  --application-id com.amphion.asr.sample --customer "Internal Test" --expires 2099-01-01 \
  --features ASR --out sample/src/main/assets/amphion-license.lic
./gradlew :samples:public-demo:installRelease   # sample release minify=true，同时回归 SDK consumer-rules
```

- [ ] 武装构建 + 放入对应 `.lic` 后，`AmphionRuntime.licenseStatus().state == LICENSED`
- [ ] 故意删掉 `.lic` 重启：ENFORCE 模式下 `AmphionRuntime.init` 抛 `code=6001`
- [ ] 故意把 `.lic` 改 1 个字节重启：抛 `code=6003`（验签失败）
- [ ] release 包真机回归：开启 R8 后录音 / 切语言 / 标点 / ITN 全链路正常（验证混淆未误伤验签与 JNI）

> SDK 自 0.2.x 起 release 默认 `isMinifyEnabled=true`（让 internal 验签逻辑在 AAR 中被混淆），改动后这一步真机回归是强制项；任何 R8 误裁剪都要补 `consumer-rules.pro` 的 keep 规则。

## 4. 交付文件准备

```bash
# 在 asr/android 下
mkdir -p ../delivery/amphion-runtime-android-0.2.0-$(date +%Y-%m-%d)
DST=../delivery/amphion-runtime-android-0.2.0-$(date +%Y-%m-%d)

cp sdk/build/outputs/aar/sdk-release.aar               $DST/amphion-runtime-0.2.0.aar
cp sdk/build/maven-repo/.../amphion-runtime-0.2.0-sources.jar $DST/  # 可选
cp docs/INTEGRATION.md docs/PRIVACY.md docs/CHANGELOG.md $DST/
cp ../../LICENSE ../../NOTICE                          $DST/
cp sdk/consumer-rules.pro                              $DST/
cp sample/src/main/java/com/amphion/asr/sample/MainActivity.kt $DST/samples/

(cd $DST && shasum -a 256 *.aar *.jar > checksum.txt)
```

最后压一个 zip 发过去（或者发到内部资产仓库 / 链接）：

```bash
cd ../delivery
zip -r amphion-runtime-android-0.2.0-2026-05-25.zip amphion-runtime-android-0.2.0-2026-05-25/
```

## 5. 给业务方的最小化沟通模板

```
Subject: Amphion ASR Android SDK v0.2.0 交付

附件：amphion-runtime-android-0.2.0-2026-05-25.zip (sha256: <填一下>)

主要说明：
1. 单 AAR 交付，模型已经打包，无需任何 CDN / 模型分发
2. 公开 API 4 个（AmphionRuntime / AsrEngine / AsrSession / AsrCallback）+ 几个 data class，
   集成最小代码 ~30 行，见 INTEGRATION.md §5
3. AAR 体积 280 MB；APK 安装后首次启动会有 5-30s 的解包阶段，
   强烈建议在 splash 调 AmphionRuntime.preload(ctx, listOf(ZH_EN, YUE_EN)) 一次完成
   解包 + 多语言加载，常驻 RSS ~180 MB；之后切语言 ~100 ms 无感（详见 INTEGRATION.md §11）
4. 仅 arm64-v8a；不需要 INTERNET 权限；不会发起任何网络请求
5. 端侧标准指标默认通过 logcat tag=AmphionMetrics 输出（KV 行）；业务方需要自定义
   监控时实现 AsrCallback.onMetrics(metrics)，字段见 INTEGRATION.md §12

后续：
- 用真机（确认是 Android 12 / HarmonyOS 4.3）跑一遍 INTEGRATION.md §5 的最小代码，
  通通通过后我们再封装下一版
- 任何报错请把 logcat 中 tag=AmphionRuntime 与 tag=AmphionMetrics 的全部行回传
```

## 6. 升级 / 出新版本的 SOP

### 6.1 模型版本号怎么走

- AAR 整包版本号：`gradle.properties.AMPHION_RUNTIME_VERSION` (SemVer)
- 单份模型版本号：`AssetRegistry.kt` 里硬编码的 `<bundleId>/v<n>` 形如 `zh-en/v1`、`zh-en/v2`
- 升级单份模型 = bump 这个子目录 + 重发 AAR；不需要业务方做任何配置

### 6.2 升级步骤

1. 重训 / 重量化 / 重打包某份模型
2. 改 `asr/tools/08_pack_sdk_assets.sh` 里的源路径 / 文件名（如有）
3. 必要时 bump `AssetRegistry.kt` 里的 `bundleId`（如 `zh-en/v1` → `zh-en/v2`）
4. bump `gradle.properties.AMPHION_RUNTIME_VERSION`（每次出 AAR 都要 bump）
5. 跑完 §3 的 3.3 / 3.4 / 3.5
6. 更新 `docs/CHANGELOG.md`，重点说清楚:
   - 哪些模型变了
   - 是否兼容旧 AAR（API 层面）
   - 端上需不需要重新解包（一般是要）

升级 AAR 给业务方时，因为 SDK_VERSION 已经写到 install.flag，用户首次启动新版本自动会触发重新解包；业务方代码不用改。

## 7. 故障常见 case

### 7.1 AAR 体积超预期

- 检查 sdk/src/main/assets/amphion-models/<sub>/v1/ 实际大小：`du -sh sdk/src/main/assets/amphion-models/*/v1`
- 检查 build.gradle.kts 的 `androidResources.noCompress` 是否被改掉
- 检查模型自身有没有变大（如不小心放进了 fp32 副本）

### 7.2 业务方装包后首次启动 ANR

最大原因：业务方在主线程调了 `AmphionRuntime.create`，触发了同步解包阻塞 UI。

修复：
- 让业务方把 `create` 放子线程
- 或者在 splash 阶段调 `AmphionRuntime.preInstall(ctx) { ... }`，把解包前置

### 7.3 业务方反馈识别效果差

- 先确认采样率是 16 kHz、单声道、16-bit
- 看 logcat tag = `AmphionRuntime` 是否有 `decode_failed` 或 `postprocess_failed`
- 让业务方把 `AmphionLogLevel` 调成 INFO 重启再发一段 logcat

## 8. 法务 / 合规清单

- [ ] LICENSE 文件原文不被业务方改名
- [ ] NOTICE 文件保留全部第三方声明（sherpa-onnx / WeTextProcessing / silero-vad / onnxruntime）
- [ ] 与业务方签署的 NDA 中明确 SDK 不会上传任何用户数据；本 SDK 自己也不会
- [ ] 若业务方位于欧盟 / 美国，让法务确认 PRIVACY.md 中文版需要本地化版本

## 9. 联系点 / 责任人

| 事项 | 负责人 |
| --- | --- |
| Android SDK 交付与版本管理 | (待填) |
| 模型 / 训练 | (待填) |
| 法务 / 合规 | (待填) |
| 业务方对接窗口 | (待填) |
| :samples:internal-eval 维护（评测框架跟随 SDK 升级） | (待填) |

## 10. 对内评测版 :samples:internal-eval

`:samples:internal-eval` 是对内使用的评测数据采集 App，与对外 `:samples:public-demo` 完全物理隔离：

| 维度 | :samples:public-demo（对外） | :samples:internal-eval（对内） |
| --- | --- | --- |
| applicationId | com.amphion.asr.sample | com.amphion.asr.sample.eval |
| 入口 | MainActivity（直接录音 demo） | LandingActivity → EvalActivity（句子列表 + 测试员管理 + 上传） |
| 权限 | RECORD_AUDIO | RECORD_AUDIO + INTERNET + ACCESS_NETWORK_STATE |
| 第三方依赖 | 仅 AndroidX core / appcompat / material | 额外 OkHttp + RecyclerView + lifecycle |
| FileProvider | 无 | 有（暴露导出 zip） |
| ProGuard | release minify=true，验证 SDK consumer-rules | minify=false，不对外 |
| 交付状态 | 跟随 SDK 一起交付（来源进 INTEGRATION 示例） | 永远不进交付包 |

### 10.1 设计动机

把对外 demo 与对内评测物理隔离的根因：

- 失败域：评测代码出 bug（比如 OkHttp 上传 leak）不会影响对外 demo
- 交付边界：对外业务方拿到的产物里看不到 INTERNET 权限 / 上传配置 / FileProvider 这些"对内资产"
- 维护成本：评测版用 SDK 公开 API（不开 internal 后门），自带 SDK 公开 API 的回归测试价值；SDK 升级时评测版编译报错就直接说明业务方接入也会回归

详细推导（包括为什么不选 productFlavors / git 分支）见 PR 描述与 `.cursor/plans/android_双版模块拆分_*.plan.md`。

### 10.2 评测版构建与自验

```bash
cd asr/android
./gradlew :samples:internal-eval:installDebug
adb shell am start -n com.amphion.asr.sample.eval/com.amphion.asr.sample.eval.LandingActivity
```

跑通后验证：

- [ ] LandingActivity 显示「参与测试」单卡片（demo 跳板已删）
- [ ] 进入 EvalActivity 看到句子列表 + 顶部测试员卡片
- [ ] 点击句子进入 RecordSentenceActivity，引擎卡片显示「中英 / 粤英」（不再显示 modelId）
- [ ] 录一句中文，停止后 hypothesis + 估算准确率出现，meta.json 中 model_id="ZH_EN" / model_version=SDK 版本
- [ ] meta.json 中含 on_device_utterance_e2e_ms / on_device_rtf / on_device_native_rss_mb 字段
- [ ] 切换到粤英，重新录音可正常出 hypothesis（池命中 ≤ 100ms）
- [ ] 配置上传地址后，触发立即上传可走通

### 10.3 评测版的 SDK API 用法约束

`:samples:internal-eval` 只允许使用 SDK 公开 API（`com.amphion.asr.*` 顶层）；不允许：

- 反射访问 `com.amphion.asr.internal.*`
- 通过 `@JvmField` / `@Suppress("INVISIBLE_*")` 等手段绕过 internal 可见性
- 引入 SDK 之外的模型分发链路（0.2.0 模型已内置 AAR）

需要新增评测维度（如新的 metric 字段）时按以下顺序走：

1. 在 SDK 的 `AmphionMetrics` 加字段
2. 评测版 `OnDeviceTranscriber` / `RecordingMeta` 跟进序列化
3. 必要时 bump `RecordingMeta.CURRENT_SCHEMA_VERSION` + 同步更新 `docs/eval/SCHEMA.md` 与 `docs/eval/SERVER_SPEC.md`

### 10.4 维护责任

`:samples:internal-eval` 的责任人见 §9 联系点表。SDK 公开 API 升级时该责任人需在同一 PR 内同步评测版编译；如果评测版无法跟进，PR 不允许合入主干（保护"评测版自带回归测试"的契约）。

## 11. 商用 License 签发与计费 SOP

授权方案与行业调研背景见 [LICENSING.md](LICENSING.md)；客户接入步骤见 [INTEGRATION.md](INTEGRATION.md) 的商用授权章节；签发工具见 [tools/license/README.md](../../../tools/license/README.md)。

### 11.1 角色与信任根

- 私钥（信任根）：我方唯一持有，离线保管（密码管理器 / KMS / 保险库）。泄露 = 任何人可签发有效 license，等同授权体系被攻破。严禁进库、严禁外发、严禁放 CI。
- 公钥：内置进交付 AAR（构建期注入）。换公钥 = 已签发的所有旧 `.lic` 立即失效。

### 11.2 签发流程（每个客户 / 每个 applicationId 一次）

1. 商务确认：客户主体、applicationId、装机量档位、功能模块、授权期限（订阅年限或买断）、是否绑签名证书。
2. 收集绑定信息：向客户索取 applicationId 与（建议）release 签名证书 SHA-256（`keytool -list -v -keystore <ks> -alias <a> | grep SHA256`）。
3. 签发：

```bash
python tools/license/issue_license.py \
  --private-key ~/secure/amphion-license-private.pem \
  --application-id <客户包名> --customer "<客户名>" --license-id <编号> \
  --expires <yyyy-MM-dd 或留空=永久> --install-tier <档位> \
  --features <逗号分隔> --cert-sha256 <证书SHA256或留空> \
  --out <客户包名>.lic
```

4. 自测：`python tools/license/verify_license.py --license <...>.lic --private-key <...> --application-id <客户包名>` 确认通过。
5. 登记台账（见 11.5）后，经安全渠道把 `.lic` 发给客户。

### 11.3 计费口径

- 计费单位：装机 License（按 applicationId + 装机量档位）。定价结构与档位建议见 [LICENSING.md](LICENSING.md) §6。
- 离线方案不实时计量装机量；installTier 是声明性档位，实际约束靠合同 + 抽样审计（见 11.6）。需要离线硬上限走 Phase 2 批量激活码。

### 11.4 续费

- 订阅到期前按客户主体的到期日提前提醒（建议提前 30 天）。续费即用同一私钥对同一 applicationId 重签一份更晚 expiresAt 的 `.lic`，替换客户 assets 内文件并随 App 更新下发。
- 客户端可设 `AmphionOptions.expiryGraceDays` 容忍时钟误差；不建议设很大宽限替代续期。

### 11.5 授权台账（必须维护）

每次签发登记：licenseId、客户、applicationId、certSha256、issuedAt、expiresAt、installTier、features、签发人、交付渠道。台账是审计与吊销决策的依据。

### 11.6 审计

- 合同约定我方有权抽样审计客户实际装机量 / 上架包名。
- 技术核对手段：核对线上 App 的 applicationId 与签名证书是否与 license 绑定一致（防止一份 license 跨 App 复用）。

### 11.7 吊销（离线方案的固有局限）

纯离线无服务器仲裁，无法主动召回已发的 `.lic`。可用手段，按代价从低到高：

| 手段 | 说明 | 代价 |
| --- | --- | --- |
| 短期有效期 + 续期 | 默认签发带 expiresAt，停止续期即自然失效 | 低，推荐默认 |
| 下一版 App 不再随包下发该 .lic | 依赖客户发版，旧版本仍可用 | 中 |
| 公钥轮换（核选项） | 换私钥 / 公钥重编 AAR，旧 .lic 全失效，需给所有在用客户重签重发 | 高，影响全量客户 |

结论：把有效期做短（订阅制）是离线方案最务实的吊销手段；买断客户的吊销基本只能靠法务。

### 11.8 公钥轮换 SOP

1. `gen_keypair.py` 生成新密钥对，安全归档旧私钥（用于必要时验证历史签发）。
2. 更新 gradle.properties 公钥，bump SDK 版本，重编 AAR。
3. 对所有在用客户用新私钥重签 `.lic` 并随新版 AAR 下发。
4. 更新台账标注轮换日期与受影响 licenseId。
