# 构建与验证

本文面向第一次拿到这份 HarmonyOS 工程的协作者，目标是从 0 构建出 HAR，并理解 `sample` 这个宿主 HAP 的用途。

最终 SDK 产物：

```text
sdk/build/default/outputs/default/sdk.har
```

宿主 HAP 构建产物：

```text
sample/build/default/outputs/default/sample-default-unsigned.hap
```

## 0. 最短路径

如果你只想最快跑通，按下面 5 步做：

1. 把完整模型包放到：

```text
LitsTtsSdk\tools\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

2. 进入：

```text
LitsTtsSdk\HarmonyOS\AmphionRuntime
```

3. 运行宿主侧预检：

```powershell
node ..\..\tools\verify_lits_harmony_package.mjs --model-dir ..\..\tools\trial-export\lits_delivery_16k_hifigan\1.0.0 --out-dir .\verification\out --text "Hello world." --mode en-US
```

4. 设置环境变量：

```powershell
$env:DEVECO_SDK_HOME="C:\Program Files\Huawei\DevEco Studio\sdk"
$env:JAVA_HOME="C:\Program Files\Huawei\DevEco Studio\jbr"
```

5. 构建 HAR：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sdk@default assembleHar --analyze=normal --parallel --incremental --no-daemon
```

## 1. 环境前提

构建 `sdk/` 至少需要：

- DevEco Studio 6.x 或其配套 Command Line Tools
- HarmonyOS SDK `6.0.2.130`
- Node.js
- Java 17
- 完整模型包 `lits_delivery_16k_hifigan/1.0.0`

建议显式设置：

```powershell
$env:DEVECO_SDK_HOME="C:\Program Files\Huawei\DevEco Studio\sdk"
$env:JAVA_HOME="C:\Program Files\Huawei\DevEco Studio\jbr"
```

如果你机器上 PATH 里混入了别的损坏 JDK，`JAVA_HOME` 不指向 DevEco 自带 JBR 时，`hvigor` 或 `hap-sign-tool.jar` 可能直接失败。

## 2. 模型包准备

把完整模型包放到：

```text
LitsTtsSdk\tools\trial-export\lits_delivery_16k_hifigan\1.0.0\
```

最少需要以下文件：

- `manifest.json`
- `lits_acoustic.onnx`
- `hifigan_vocoder.onnx`
- `smoke_tokens.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`

注意：

- 不需要 checkpoint
- 不需要执行任何导出脚本
- 不要把模型手工拷进 `sdk/` 或 `sample/`

HarmonyOS SDK 会在构建阶段把 `tools/trial-export/...` 同步进 `sdk/src/main/resources/rawfile/...`，并在运行时默认使用 HAR 内置模型；如果宿主显式传入外部模型目录，则显式路径优先。

## 3. 宿主侧预检

执行：

```powershell
node ..\..\tools\verify_lits_harmony_package.mjs --model-dir ..\..\tools\trial-export\lits_delivery_16k_hifigan\1.0.0 --out-dir .\verification\out --text "Hello world." --mode en-US
```

这个脚本只做宿主侧预检，验证：

- 模型包文件是否齐全
- `manifest.json`、词典和 token 表是否可解析
- 英文 smoke 文本能否生成正确 token id
- 是否能生成一份确定性的本地 PCM 文件

它不会执行 HarmonyOS native ONNX 推理。真实 acoustic/vocoder 推理发生在 HAR/HAP 运行时。

成功后会产出：

```text
verification/out/lits_harmony_smoke.pcm
verification/out/verification_report.json
```

## 4. 构建 HAR

在 `LitsTtsSdk\HarmonyOS\AmphionRuntime` 目录执行：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sdk@default assembleHar --analyze=normal --parallel --incremental --no-daemon
```

成功后产物在：

```text
sdk/build/default/outputs/default/sdk.har
```

这个 HAR 才是最终 SDK 交付物。

## 5. 构建宿主 HAP

`sample/` 只用于验证 HAR 接入，不是最终 SDK 产物。

执行：

```powershell
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sample@default assembleHap --analyze=normal --parallel --incremental --no-daemon
```

成功后产物在：

```text
sample/build/default/outputs/default/sample-default-unsigned.hap
```

## 6. 真机安装说明

`sample-default-unsigned.hap` 不能直接安装。要在真机上验证 `sample/`，你必须使用设备信任的调试签名。

推荐做法：

1. 用 DevEco Studio 打开 `HarmonyOS/AmphionRuntime`
2. 给 `sample` 配置你自己的 HarmonyOS debug signing
3. 让 DevEco Studio 构建并安装 `sample`

仓库不会提交以下个人材料：

- `.p12`
- `.cer`
- `.p7b`
- 任何自动签名生成的本地缓存

## 7. 本地已验证结果

当前工作区已完成的验证有：

- `verify_lits_harmony_package.mjs` 预检成功
- `assembleHar` 成功
- `assembleHap` 成功
- 使用 OHOS native ONNX Runtime 的 HAR 能通过编译并打包进宿主 HAP

当前工作区未完全打通的一步：

- 在当前这台 HarmonyOS 真机上，使用 OpenHarmony 演示证书链手工签出的 HAP 仍然安装失败，设备返回：

```text
code:9568257 error: fail to verify pkcs7 file
```

这是签名信任问题，不是 HAR 构建问题。对接手人来说，下一步不是改 SDK 代码，而是改用当前设备信任的调试签名重新签 `sample`。

## 8. 当前限制

- 推理调用当前是同步的，单次 native 推理不可中断
- 默认模型会打进 HAR；如果宿主显式传入外部模型目录，则显式路径优先
- `sample/` 只覆盖最小闭环验证，不是正式产品级 Demo
