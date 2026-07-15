# HarmonyOS SDK 交付 SOP

本文定义从当前仓库源码生成鼎桥 HarmonyOS SDK 交付物的唯一流程。交付目录结构、输入来源、
验证方式都以本文和当前分支脚本为准，不以任何上一版本 ZIP/HAR/HAP 为模板。

## 基本原则

- 上一版本交付包只能用于历史差异对照，不得作为模型、native、HAR、HAP、文档或目录结构的输入。
- 正式交付必须从干净的 release commit 构建；`--allow-dirty` 只能生成本地诊断包。
- 交付对象是 SDK HAR。demo/HAP 只是构建和 USB 真机测试载体，不能代替 SDK 公共 API 验收。
- 打包前测试源码构建产物，打包后必须再测试“最终 ZIP 中解出的 HAR”。两者哈希不同时，前者结果无效。
- 每次交付都保留源码 commit、模型/native 身份、ZIP/HAR SHA-256、设备信息、测试参数和完整 artifact。

## 工程与输入

| 路径 | 用途 |
| --- | --- |
| `asr/harmony/` | `amphion_asr`、`amphion_police`、`amphion_dingqiao` HAR 源码 |
| `tts/harmony/` | 可选的 `amphion_tts` HAR 源码 |
| `delivery/harmony-dingqiao/` | 客户宿主、文档、打包与真机验收脚本 |
| `third_party/sherpa-onnx/` | 固定 submodule 与本仓库 patch 后的 native/HAR 输入 |
| `asr/tools/demo-model/` | 受控 ASR 模型源，本地准备且不入库 |
| `.secure/` | 本地签名、license 私钥和设备清单，不入库、不进客户包 |

正式 `zhen` 输入至少包含 `encoder.int8.onnx`、`decoder.int8.onnx`、
`joiner.int8.onnx`、`tokens.txt` 和 `bbpe.vocab`。公开 demo 下载脚本不是正式模型源。
模型源 SHA-256 和转换器身份见 [`MODEL_LOAD_PERFORMANCE.md`](./MODEL_LOAD_PERFORMANCE.md)。

## 交付形态和清单

先按客户合同选择交付形态，再运行脚本。不得先打一个大包，再参照旧 ZIP 手工删文件。

| 形态 | 当前脚本入口 | 必需内容 |
| --- | --- | --- |
| ASR + TTS | 无模式参数 | ASR HAR、TTS HAR、demo HAP、TTS 模型、文档 |
| ASR + demo | `--asr-only` | ASR HAR、demo HAP、文档 |
| ASR SDK-only | 当前 `main` 尚无独立模式 | ASR HAR、文档；发布前必须先给脚本增加并测试显式模式 |

SDK-only 不允许通过复制上一版目录或从 `--asr-only` 输出中手工删除 demo 得到。若合同要求
SDK-only，而当前分支 `--help` 没有对应选项，打包工具支持本身就是该 release 分支的前置任务。

当前 ASR + demo 包的规范结构如下；文件存在性由打包脚本校验，不需要查看旧交付包：

```text
dingqiao-harmony-delivery-<version>/
├── har/
│   └── amphion_dingqiao.har
├── demo/
│   └── dingqiao-demo.hap
└── docs/
    ├── BUILD_PROVENANCE.json
    ├── CHANGELOG.md
    ├── DINGQIAO_INTEGRATION.md
    ├── DINGQIAO_LICENSE_SCHEME.md
    ├── LICENSE.md
    ├── MODEL_LOAD_PERFORMANCE.md
    ├── NOTICE
    ├── PRIVACY.md
    ├── SDK_LIFECYCLE_PERFORMANCE_20260713.md
    ├── SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md
    ├── checksum.txt
    ├── third-party/Apache-2.0.txt
    └── 语音识别SDK接口.md
```

完整包在此基础上增加 `har/amphion_tts.har` 与 `tts-models/amphion-tts/`。发布脚本是清单的
可执行来源；若本文与脚本不一致，停止交付并在同一个变更中同步两者，不能自行猜测。

## 1. 建立发布工作区

从最新 `main` 建立 release 分支和独立 worktree，避免本地开发残留进入产物：

```bash
git fetch origin
git worktree add ../AmphionRuntime-release -b release/harmony-sdk-<version> origin/main
cd ../AmphionRuntime-release
git submodule update --init third_party/sherpa-onnx
test -z "$(git status --porcelain)"
```

确认本次版本在以下公共位置一致：`asr/harmony/**/oh-package.json5`、
`delivery/harmony-dingqiao/oh-package.json5`、demo entry package、两个 `AppScope/app.json5`、
`Runtime.SDK_VERSION`、CHANGELOG 和打包变量。当前仓库仍有历史版本字段，不能只设置
`AMPHION_RUNTIME_VERSION` 就认为版本已同步。

```bash
rg -n 'AMPHION_RUNTIME_VERSION|SDK_VERSION|"version"|versionName' \
  asr/harmony delivery/harmony-dingqiao \
  --glob '!**/build/**' --glob '!**/.hvigor/**'
```

## 2. 从受控输入构建

先准备受控模型、签名和设备清单，再从当前 worktree 构建。禁止从旧 ZIP/HAR/HAP 解包补齐
缺失资产。

```bash
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash asr/tools/08_pack_harmony_assets.sh

# 仅完整 ASR + TTS 交付需要
bash tts/tools/harmony/pack_harmony_tts_assets.sh
```

`04_build_harmony_so.sh` 会应用 `third_party/patches/sherpa-amphion/`。不要提交 sherpa submodule
工作区改动或擅自改变 submodule 指针。`08_pack_harmony_assets.sh` 使用固定 ONNX Runtime 1.16.3
环境生成 Harmony ORT 资产。

随后用 DevEco/Hvigor 构建以下模块：

- `third_party/sherpa-onnx/.../sherpa_onnx`
- `asr/harmony/sdk`
- `asr/harmony/sdk-police`
- `asr/harmony/sdk-dingqiao`
- `delivery/harmony-dingqiao` 的 signed `dingqiao_demo` HAP
- 完整包额外构建 `tts/harmony/sdk`

推荐由统一入口完成签名 HAP 构建、校验、安装和 UI smoke：

```bash
HARMONY_SIGNING_CONFIG=.secure/harmony-signing.json \
  delivery/harmony-dingqiao/delivery/build_install_smoke.sh --device <HDC_TARGET>
```

签名文件格式见 `delivery/harmony-dingqiao/delivery/harmony-signing.example.json`。文件权限应为
`600`。设备绑定 license 使用的 ODID/SN 清单必须与宿主实际标识类型一致。

## 3. 打包前 SDK 门禁

先运行单元测试和 Harmony 编译，再按 [`DEVICE_STRESS.md`](./DEVICE_STRESS.md) 的发布矩阵测试。
最低要求包含：

```bash
python3 -m unittest \
  asr.tools.tests.test_harmony_initial_silence_tracker \
  asr.tools.tests.test_harmony_rejected_final_lifecycle \
  delivery.harmony-dingqiao.delivery.test_run_device_stress -v

python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py \
  --skip-build --device <HDC_TARGET> --warmup-runs 2 --iterations 10

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --skip-build-install --device <HDC_TARGET> --data-dir <WAV_DIR> \
  --mode user-sequence --cycles 300 --files 3
```

加载基准的模型/native/HAP 身份必须与本次构建一致，比较规则见
[`MODEL_LOAD_PERFORMANCE.md`](./MODEL_LOAD_PERFORMANCE.md)。这一步用于尽早发现源码构建问题，
但不是最终交付验收。所有结果必须记录唯一 output root，失败 artifact 不得被后续运行覆盖。

## 4. 生成交付目录

正式打包必须保持工作区干净，并显式设置版本：

```bash
export AMPHION_RUNTIME_VERSION=<version>
export HARMONY_SIGNING_CONFIG="$PWD/.secure/harmony-signing.json"

# ASR + demo
bash delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh \
  --asr-only "build/dingqiao-harmony-delivery-${AMPHION_RUNTIME_VERSION}"
```

完整 ASR + TTS 包去掉 `--asr-only`。脚本会原子组装目录、自包含 ASR HAR、在干净客户宿主中
仅依赖该 HAR 完成安装和编译、验证 HAP/模型/native 身份，并生成 `BUILD_PROVENANCE.json` 与
`checksum.txt`。任何必需产物缺失都必须失败，不能用 warning 继续发布。

## 5. 生成并校验最终 ZIP

ZIP 名称包含版本和日期，但验收身份以 SHA-256 为准：

```bash
VERSION=<version>
DATE=$(date +%Y%m%d)
DIR="build/dingqiao-harmony-delivery-${VERSION}"
ZIP="build/dingqiao-harmony-asr-sdk-${VERSION}-${DATE}.zip"

(cd "$(dirname "$DIR")" && /usr/bin/zip -qry "$(basename "$ZIP")" "$(basename "$DIR")")
shasum -a 256 "$ZIP" > "${ZIP}.sha256"

VERIFY_DIR=$(mktemp -d)
unzip -q "$ZIP" -d "$VERIFY_DIR"
(cd "$VERIFY_DIR/$(basename "$DIR")" && shasum -a 256 -c docs/checksum.txt)
tar tzf "$VERIFY_DIR/$(basename "$DIR")/har/amphion_dingqiao.har" >/dev/null
```

再检查 ZIP 内：

- 目录仅包含所选交付形态的规范清单，不含绝对路径、`.secure/`、源码构建缓存或测试语料。
- `BUILD_PROVENANCE.json` 的 commit、branch、版本、模型/native/HAR/HAP 哈希与本次记录一致。
- `CHANGELOG.md`、接口文档和实际公共 API 一致。
- `docs/checksum.txt` 全量通过；ZIP 与 HAR 的 SHA-256 已记录到交付报告。

## 6. 用最终 ZIP 做真机 SDK 验收

最终真机门禁的 SDK 输入必须是上一步临时目录中解出的 `amphion_dingqiao.har`，不是源码目录里
先前构建的 HAR。测试载体的依赖应只声明：

```json
{
  "dependencies": {
    "amphion_dingqiao": "file:./libs/amphion_dingqiao.har"
  }
}
```

先执行 `verify_selfcontained_dingqiao_har.sh <解包后的 HAR>` 验证纯客户宿主可安装和编译，再用
该 HAR 构建 signed 压测载体并运行完整发布矩阵。当前 `run_device_stress.py` 没有 `--sdk-har`
参数，因此不得假装 `--skip-build-install` 已验证最终 ZIP；release 分支应先提供 artifact-driven
载体入口，或保留一份可审计的临时客户宿主构建记录。给脚本增加入口时，必须记录 ZIP/HAR hash，
且不得回退引用仓库内 HAR。

真机测试只判定 SDK 生命周期、回调归属、资源回收和声纹分数可选性，不用识别准确率或相似度
数值作为 PASS 条件。详细模式、轮次预算和语料准入见 [`DEVICE_STRESS.md`](./DEVICE_STRESS.md)。

## 7. 交付记录与放行

每版至少归档：

- release commit、branch、`git status --porcelain` 为空的证据。
- ZIP 文件名、大小、SHA-256；ZIP 内 HAR 的 SHA-256。
- `BUILD_PROVENANCE.json` 和 `checksum.txt` 校验结果。
- DevEco、Harmony SDK、设备型号、系统版本、设备 ID 的脱敏标识。
- 每个必跑模式的命令、轮数、结果和 artifact 路径。
- 未覆盖的外部故障、`INCONCLUSIVE` 资源结论和已接受风险。

仅当最终 ZIP 的清单/校验通过、纯客户宿主编译通过、最终 ZIP HAR 的必跑真机门禁通过，且没有
未处理的 PR 阻断评论时才可交付。不能用“上一版结构相同”“demo 能打开”或“源码构建测过”代替。

## TTS

离线 TTS 是独立 SDK `amphion_tts`。仅当合同明确包含 TTS 时，才准备 TTS 模型、构建 TTS HAR
并选择完整包；ASR-only/SDK-only 流程不得隐式携带 TTS 资产。
