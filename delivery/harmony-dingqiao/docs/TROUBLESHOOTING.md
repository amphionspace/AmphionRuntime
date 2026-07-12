# HarmonyOS Demo 故障排查

## 先运行自动检查

```bash
delivery/harmony-dingqiao/delivery/verify_demo_inputs.sh
HARMONY_SIGNING_CONFIG=.secure/harmony-signing.json \
  delivery/harmony-dingqiao/delivery/build_install_smoke.sh
```

第一条在构建前检查模型、AArch64 native 库、license 签名/有效期/设备白名单。第二条在隔离的临时工程中完成 signed HAP 构建，再用 DevEco `hap-sign-tool.jar` 检查应用签名、profile、包身份和预期证书链，最后覆盖安装到 USB 设备并等待页面显示“引擎就绪”。失败日志保存在 `delivery/harmony-dingqiao/build/smoke/`。

签名配置必须是权限为 `600` 的本地 JSON，格式见 `delivery/harmony-dingqiao/delivery/harmony-signing.example.json`。仓库不保存证书路径、keystore 口令或 profile 口令，构建过程也不会改写仓库内的 `build-profile.json5`。证书链过期会在构建前失败。

## `授权文件准备失败：Error: Invalid relative path`

原因是 `resources/rawfile/amphion-license.lic` 没有进入 HAP，或代码读取的 rawfile 相对路径不一致。

检查：

```bash
unzip -l path/to/dingqiao_demo-default-signed.hap | grep amphion-license.lic
```

不要只检查源码目录；最终验收对象是 signed HAP。

## `1002200033 device not authorized`

可能原因：

- license 中存在设备哈希，但 `deviceIdProvider` 没有返回标识。
- 签发使用硬件 SN，运行时返回 ODID，或反向混用。
- 当前设备尚未加入签发清单。
- 普通应用尝试读取需要 `ohos.permission.sec.ACCESS_UDID` 的 `deviceInfo.serial`。

普通 Demo 固定使用 `deviceInfo.ODID`，其签发清单默认是 `.secure/dingqiao_demo_device_ids.txt`；系统/预置宿主使用硬件 SN，并通过 `DINGQIAO_DEVICE_ID_FILE` 指定独立清单。不要把两类标识混在同一验收流程中，也不要把明文设备标识写入源码、HAP 或公开日志。

## `No graph was found in the protobuf`

这表示 ONNX Runtime 收到了错误文件、空内容或错误 rawfile 路径。重点检查 `amphion-models/<bundle>/v1/` 目录层级，以及模型是否与 `manifest.json` 的大小和 SHA-256 一致：

```bash
python3 asr/tools/verify_packed_model_assets.py \
  --root asr/harmony/sdk/src/main/resources/rawfile/amphion-models
```

当前 NAPI 边界会把 recognizer 创建异常转成 ArkTS 异常；无效模型应显示“引擎初始化失败”，不应再触发 App `SIGABRT`。

当前 `zhen` 正式交付使用 manifest v2 和
`zh-en/v1/{encoder.int8.ort,decoder.ort,joiner.int8.ort}`。如果 HAP 仍包含 ONNX 三图、
manifest v1，或 HAP 内 manifest/native 与本地验收产物不同，说明混入了旧构建产物；重新执行
模型打包和 `build_install_smoke.sh`，不要直接复用旧 HAP。

## 冷加载回退

先运行独立进程基准，不要用页面打开时间代替模型加载时间：

```bash
python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py \
  --skip-build --device <HDC_TARGET> --warmup-runs 2 --iterations 10
```

报告的 comparison identity 必须显示 4 threads、0 warmup samples、punctuation loaded，并与
待比较基线具有相同设备构建和模型源 SHA-256。当前 `zhen` 参考值和常见误判见
[`MODEL_LOAD_PERFORMANCE.md`](./MODEL_LOAD_PERFORMANCE.md)。

## 真机日志

清空和导出日志应通过设备 shell 执行：

```bash
hdc shell hilog -r
hdc shell hilog -x > hilog.txt
```

不要使用会保持流式读取的 `hdc hilog -r` 组合，否则自动化任务可能一直等待。
