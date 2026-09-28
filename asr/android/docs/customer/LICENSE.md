# 离线授权接入说明（Android ASR）

交付 AAR 已启用离线验签，集成方无需配置或替换公钥。授权文件由签发方受控提供，具体能力、期限、设备白名单、证书、主版本和维护期以本批授权声明为准。

## 授权范围

- 必须包含 ASR 能力；只有同时包含 TTS 且满足其绑定条件时才可供 TTS 共用。
- Android ASR 不校验包名；Android TTS 仍校验非空 applicationId（为空时回退 bundleName）。不绑定应用的共用授权须将两字段均留空，应用标识只记签发登记。
- 含设备白名单时，宿主须能提供与签发依据一致的稳定 SN；未绑定设备的体验授权不需要为此读取 SN。
- Demo 授权仅证明其自身范围内的体验可用，不能替代正式宿主对实际授权文件的验证。

## 调用顺序

将授权文件放到应用私有可读路径；若放在 assets，应先复制为文件，再传绝对路径。

```kotlin
SpeechRecognizeSdk.init(applicationContext)
SpeechRecognizeSdk.setWorkPath(workPath)
SpeechRecognizeSdk.setLicense(licenseAbsolutePath, object : LicenseActivationCallback {
    override fun onResult(result: LicenseActivationResult) {
        if (result.errorCode != 0) return
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                // 此后调用 createEngineAsync，成功后设置监听器并开始识别。
            }
            override fun onError(errorCode: Int, errorMessage: String) {
                // Runtime 准备失败，停止本次识别启动。
            }
        })
    }
    override fun onError(errorCode: Int, errorMessage: String) {
        // 授权失败，提示并停止本次识别启动。
    }
})
```

`init` 设置上下文与设备标识来源，不等于授权成功；`setLicense` 仅验权和缓存，`prepareRuntime` 才准备运行时及默认模型。不能省略任一步或在就绪回调前启动引擎。需要自定义 SN 时使用 `init(context, LicenseDeviceIdProvider)`，见 [DINGQIAO_INTEGRATION.md](DINGQIAO_INTEGRATION.md)。

## 错误处理

| 错误码 | 含义与处理 |
| --- | --- |
| `1002200030` | 文件缺失或不可读，检查绝对路径及权限 |
| `1002200031` | 格式、签名、SDK 主版本或授权能力无效，核对并重新获取授权 |
| `1002200032` | 运行期限或维护期不满足，联系重新签发 |
| `1002200033` | 设备不可用、不匹配或证书不匹配，核对本批白名单、provider 及签名 |
| `1002200034` | 未设置授权，先等待 setLicense 成功 |
| `1002200035` | 激活失败，结合脱敏错误信息排查能力/版本等条件 |

Android 与 Harmony 的适配层均将本地设备/证书绑定错误收敛到 `1002200033`，不单独回调 0036/0037。以上是鼎桥公共 API 错误码，底层 `AmphionRuntime` 的 600x 错误码不能直接当作适配层错误码使用。完整定义见 [语音识别SDK接口.md](语音识别SDK接口.md)。

不要将授权原文、SN、私钥或证书口令写入公开日志或源码仓库。授权变更后重新完成验权与 Runtime 准备。
