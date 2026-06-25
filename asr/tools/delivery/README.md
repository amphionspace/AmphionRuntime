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

溯源逻辑见 `asr/android/docs/DINGQIAO_DELIVERY.md` §4.1。
