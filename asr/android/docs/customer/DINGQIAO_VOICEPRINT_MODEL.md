# 声纹模型部署说明（eres2net.onnx）

面向鼎桥集成与 Demo 验收。SDK 交付包 `models/` 目录下已含该文件，**运行时需自行拷贝到设备工作目录**。

---

## 1. 与 ASR 模型的区别

| 类型 | 是否在 AAR 内 | 是否需要手动下发 |
|------|----------------|----------------|
| **ASR 声学模型**（识别用） | 是 | 否，首次运行自动解包 |
| **声纹模型** `eres2net.onnx` | 否 | **是**，须放到 `setWorkPath` 目录 |

Demo 提示「未找到声纹模型」，一般指 **App 读不到模型文件**（路径不对，或 adb push 后文件属主为 root），不是 ASR 模型缺失。

---

## 2. 文件要求

- **类型**：`eres2net.onnx` 是**单个模型文件**（约 38 MB），不是文件夹；手机文件管理器可能把它显示成「空文件夹」，可忽略
- **文件名**：必须为 `eres2net.onnx`
- **位置**：`{setWorkPath}/eres2net.onnx`（工作目录**根下**）

---

## 3. 官方 Demo APK（`com.amphion.dingqiao.demo`）

Demo 默认工作目录：

```
/sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/
```

### 方式 A（推荐，普通手机无需 root）

1. 将交付包 `models/eres2net.onnx` 拷到手机「下载 / Download」目录（数据线、微信、邮件均可）
2. 打开 Demo → 菜单 **「导入声纹模型」**（或声纹注册页同名按钮）→ 选中该文件
3. 提示「声纹模型已导入」后，录制至少 1 段样本注册；多段样本可提升稳定性

### 方式 B（adb，注意文件属主）

**不要**只执行 `adb push` 到 `dingqiao_work/` 就结束。截图里若看到：

```
-rw-r--r-- root root ... eres2net.onnx
```

而旁边 `enroll_samples` 属主是 `u0_aXXX`，说明模型是 root 推送的，**Demo App 无法读取**，注册会失败。

推荐 adb 流程：

```bash
# 1. 先安装 Demo 并启动一次（创建 dingqiao_work）
# 2. 推到公共「下载」目录（Demo 启动时会尝试自动复制）
adb push eres2net.onnx /sdcard/Download/eres2net.onnx

# 3. 重新打开 Demo，或在 App 内「导入声纹模型」
```

若必须直接 push 到工作目录，需把属主改成与 `enroll_samples` 一致（部分机型需 `adb root`）：

```bash
adb push eres2net.onnx /sdcard/Android/data/com.amphion.dingqiao.demo/files/dingqiao_work/eres2net.onnx

PKG=com.amphion.dingqiao.demo
WORK=/sdcard/Android/data/$PKG/files/dingqiao_work
adb shell "chown \$(stat -c %u:$WORK/enroll_samples):\$(stat -c %g $WORK/enroll_samples) $WORK/eres2net.onnx"
adb shell ls -l $WORK/
```

成功时 `eres2net.onnx` 属主应与 `enroll_samples` 同为 `u0_aXXX`，大小约 **38 MB**。

---

## 4. 正式 App（`com.tdtech.tiassistant`）

路径取决于贵司 `SpeechRecognizeSdk.setWorkPath(...)` 的配置。模型须由 **App 自己写入** 工作目录（集成时从 assets 解压、或从贵司下发通道拷贝），不要依赖 adb 直接 push 到 `Android/data/`（同样会遇到属主/权限问题）。

---

## 5. 常见错误

| 现象 | 可能原因 |
|------|----------|
| adb `ls` 能看到文件，Demo 仍提示找不到 | 文件属主为 `root`，App 不可读 → 用「导入声纹模型」或修正 chown |
| 文件管理器点开 onnx「文件夹」为空 | 正常误解；它是模型文件，请用 App 导入 |
| 注册失败 `speaker model not found` | 同上，或文件名/路径不对 |
| 注册失败 `sample duration` | 每段样本须 3～8 秒 |

---

## 6. 验收建议

1. Demo 主界面不再显示「未找到声纹模型」
2. 声纹注册页 → 录制至少 1 段 → 注册成功
3. 主界面开启「声纹校验」后识别，final 结果应带相似度字段

更多集成说明见 `DINGQIAO_INTEGRATION.md`。
