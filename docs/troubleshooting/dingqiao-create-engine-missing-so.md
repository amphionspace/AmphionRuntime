# 鼎桥 Android createEngine 找不到 so 复盘

## 问题复述

表面现象是客户接入新 ASR SDK 后 `createEngine` 失败，日志里出现 `java.lang.UnsatisfiedLinkError: dlopen failed` 或 `libsherpa-onnx-jni.so not found`。

真正问题是交付包里的 AAR/APK 没有包含 sherpa JNI 和 ONNX Runtime native 库，导致 Kotlin 层执行 `System.loadLibrary("sherpa-onnx-jni")` 时必然失败。

## 关键事实

- Android 运行时不会从模型目录或 assets 里加载 `.so`，只能从 APK 安装后的 native lib 路径加载。
- AAR 中 native 库必须位于 `jni/<abi>/`，合入 APK 后会变成 `lib/<abi>/`。
- 当前鼎桥 Android 交付只支持 `arm64-v8a`。
- `libsherpa-onnx-jni.so` 依赖 `libonnxruntime.so`，两者必须同时在包内。

## 本次证据

旧包：

```bash
bash asr/tools/delivery/verify_dingqiao_delivery.sh \
  /Users/boxp/workspace/delivery/amphion-dingqiao-v0.2.6-customer-20260624.zip
```

预期失败信息：

```text
[ERROR] AAR missing required native libs:
  - jni/arm64-v8a/libsherpa-onnx-jni.so
  - jni/arm64-v8a/libonnxruntime.so
```

新包：

```bash
bash asr/tools/delivery/verify_dingqiao_delivery.sh \
  /Users/boxp/workspace/delivery/amphion-dingqiao-v0.2.6-customer-20260625.zip
```

预期通过信息：

```text
[OK] AAR native lib present: jni/arm64-v8a/libsherpa-onnx-jni.so
[OK] AAR native lib present: jni/arm64-v8a/libonnxruntime.so
[OK] APK native lib present: lib/arm64-v8a/libsherpa-onnx-jni.so
[OK] APK native lib present: lib/arm64-v8a/libonnxruntime.so
```

## 根因层级

根因在交付构建层，不在客户集成层，也不是 `createEngine` 代码逻辑问题。

原始流程把 native 库拷贝作为人工前置步骤，但验收脚本只检查版本溯源、NOTICE、zip 编码，没有检查 AAR/APK 里是否真的有必需 `.so`。因此一个缺 native 库的包仍然可以被打出并交付。

## 预防措施

正式客户包脚本必须执行严格 native 拷贝：

```bash
AMPHION_REQUIRE_ANDROID_NATIVE_LIBS=1 \
  bash asr/tools/05_package_aar_libs.sh arm64-v8a
```

如果 `third_party/sherpa-onnx/build-android-arm64-v8a/install/lib/` 不存在，或缺少以下文件，脚本必须失败：

```text
libsherpa-onnx-jni.so
libonnxruntime.so
```

fat AAR 合并后必须检查：

```text
jni/arm64-v8a/libsherpa-onnx-jni.so
jni/arm64-v8a/libonnxruntime.so
```

Demo APK 生成后必须检查：

```text
lib/arm64-v8a/libsherpa-onnx-jni.so
lib/arm64-v8a/libonnxruntime.so
```

交付 zip 或解压目录验收时，也必须检查内嵌 AAR 与 Demo APK，不能只看 `VERSION.txt`。

## 正式发包检查

```bash
# 仓库必须 clean。只允许本地预览时使用 DINGQIAO_ALLOW_DIRTY=1。
git status --short

# 正式客户包。
bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh

# 验 zip。
bash asr/tools/delivery/verify_dingqiao_delivery.sh \
  /path/to/amphion-dingqiao-v0.2.6-customer-YYYYMMDD.zip

# 验解压目录。
bash asr/tools/delivery/verify_dingqiao_delivery.sh \
  /path/to/amphion-dingqiao-v0.2.6-customer/
```

## 已知未知

静态验包能挡住“缺 `.so`”这类问题，但不能证明设备上所有 runtime 条件都满足。正式发包前仍建议做一次真机 smoke test：安装 Demo，初始化 SDK，执行到 `createEngine` 成功。
