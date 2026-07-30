# Android 鼎桥交付脚本

均在 **AmphionRuntime 仓库根目录**执行：

```bash
bash asr/tools/delivery/<script>.sh [交付版本号]
```

交付版本号省略时 = `asr/android/gradle.properties` 的 `AMPHION_RUNTIME_VERSION`。

| 脚本 | 说明 |
|------|------|
| `pack_dingqiao_customer_delivery.sh` | 鼎桥正式客户包 |
| `pack_dingqiao_delivery_scheme_a_aligned.sh` | 内部 scheme A aligned |
| `pack_dingqiao_delivery.sh` | 内部 scheme A（含 LICENSING） |
| `pack_dingqiao_delivery_scheme_b.sh` | scheme B 三 AAR |
| `merge_dingqiao_fat_aar.sh` | 仅 fat AAR |
| `verify_dingqiao_delivery.sh` | 校验 VERSION.txt / AAR 与 Demo APK native 库 / zip UTF-8 EFS / 交付目录 `docs/NOTICE` |
| `dingqiao_zip_utf8.py` | 交付 zip 打包（Windows 中文文件名） |
| `dingqiao_build_provenance.sh` | 共用库（勿直接运行） |

正式交付包会通过 `tools/delivery/asr_release_tracker.py` 自动生成
`docs/CHANGELOG.md`，范围是台账中同平台上一交付 commit 到当前构建 commit。
交付终检通过后，再用实际包内的 `VERSION.txt` 登记版本；完整流程见
[`delivery/ASR_SDK_RELEASE_TRACKING.md`](../../../delivery/ASR_SDK_RELEASE_TRACKING.md)。

溯源逻辑见 `asr/android/docs/DINGQIAO_DELIVERY.md` §4.1。
