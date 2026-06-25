# 交付包 zip-only 验证流程

## 问题复述

客户实际接收的是最终 zip，因此交付验证必须以最终 zip 为唯一真相，不能用项目 `build/` 产物、未重新压缩的目录或手工回写 APK 代替。

## 关键假设

| 假设 | 风险 |
| --- | --- |
| 客户只会按 zip 内文件安装、集成或编译 | 高 |
| 打包目录和最终 zip 可能因为手工签名、回写、重新压缩而不一致 | 高 |
| 不同产品的 AAR/APK/license/model 条目不同 | 中 |
| 设备验证依赖当前 USB 设备状态和授权弹窗 | 中 |

## 推荐流程

1. 先生成最终 zip。
2. 只把最终 zip 作为输入运行 `tools/delivery/verify_delivery_zip_e2e.sh`。
3. 脚本自行解压到临时目录，检查禁止文件、版本元数据、AAR/APK 必需条目、license claims、APK 签名和源码包可执行位。
4. 如需要设备验证，脚本安装 zip 解压出的 APK，不读取项目 `build/` 下 APK。
5. 如需要源码链路验证，脚本从 zip 解压出的源码工程运行 Gradle。
6. 验证通过后保留 `*.verification.json` 和 `*.verification.md`，最终回复引用报告路径和 zip SHA-256。

## 通用脚本

脚本：

```bash
tools/delivery/verify_delivery_zip_e2e.sh <delivery.zip>
```

常用环境变量：

| 变量 | 说明 |
| --- | --- |
| `DELIVERY_VERIFY_REQUIRED_AAR_ENTRIES` | AAR 内必须存在的条目，格式为 `path:min_bytes,path:min_bytes` |
| `DELIVERY_VERIFY_REQUIRED_APK_ENTRIES` | APK 内必须存在的条目，格式同上 |
| `DELIVERY_VERIFY_LICENSE_ENTRY` | APK 内 license 路径，例如 `assets/amphion-license.lic` |
| `DELIVERY_VERIFY_LICENSE_APPLICATION_ID` | license 期望绑定的应用包名 |
| `DELIVERY_VERIFY_LICENSE_FEATURES` | license 授权能力，逗号分隔 |
| `DELIVERY_VERIFY_LICENSE_DEVICE_HASH_COUNT` | license 期望设备哈希数量 |
| `DELIVERY_VERIFY_FORBIDDEN_RELATIVE_PATHS` | zip 根目录下禁止出现的相对路径，逗号分隔 |
| `DELIVERY_VERIFY_DEVICE` | 设为 `1` 时安装 zip 解压出的 APK 并启动验证 |
| `DELIVERY_VERIFY_ANDROID_PACKAGE` | 设备验证时启动的包名 |
| `DELIVERY_VERIFY_DEVICE_READY_TEXT` | 设备 UI 中必须出现的就绪文案 |
| `DELIVERY_VERIFY_DEVICE_MODEL_PATH` | 设备侧必须落盘的模型路径 |
| `DELIVERY_VERIFY_SOURCE_TEST` | 设为 `1` 时运行 zip 内源码工程设备测试 |
| `DELIVERY_VERIFY_SOURCE_DIR` | zip 解压根目录下的源码工程目录，默认 `demo-src` |
| `DELIVERY_VERIFY_SOURCE_GRADLE_TASK` | 源码工程要运行的 Gradle task |
| `DELIVERY_VERIFY_SOURCE_GRADLE_ARGS` | 源码工程测试附加参数 |

## 报告

默认输出：

| 文件 | 说明 |
| --- | --- |
| `<delivery.zip>.verification.json` | 机器可读完整报告 |
| `<delivery.zip>.verification.md` | 人工复核摘要 |

报告至少应覆盖：

- zip SHA-256 和大小
- `VERSION.txt` 中的源码 commit 和 dirty 状态
- AAR/APK 必需条目大小
- license claims 摘要
- APK 签名验证结果
- 设备验证结果
- 源码工程验证结果

## 结论

任何客户交付都应该把 zip-only 验证作为最终门禁；产品专用脚本只负责提供该产品的配置项，不应改变“从最终 zip 解压验证”的原则。
