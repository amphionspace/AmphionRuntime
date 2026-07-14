# TN 体积优化方案(端侧 TTS 文本归一化 / ICU 数据裁剪)

> 分支:`tn/icu-data-slim-proposal`(基于 `origin/lits_dingqiao_sdk_vocos24k_v3`)
> 状态:**方案已就绪,尚未构建 / 尚未验证。** 本机缺 OHOS Native SDK、ICU 工具、且 TN 源子模块未初始化,无法复现基线,因此**没有产出裁剪后的二进制,也未跑零回退门**。本文件供负责人在具备工具链的机器上构建 + 验证后再决定是否合入。
> 未改动任何交付产物(`tn-bin/arm64-v8a/{en_tts,zh_tts}` 原封不动),未 push 同事分支。

---

## 1. 根因(本机可证实的部分)

| 项 | 数值 | 证据来源 |
|---|---|---|
| 交付 `en_tts` | 37,714,920 B(≈36 MB) | `ls -l` 交付目录 |
| 交付 `zh_tts` | 37,714,872 B(≈36 MB) | `ls -l` 交付目录 |
| `libicudata.a` | 33,108,140 B(≈31.6 MB) | `ls -l ohos-icu/lib` |
| ICU 版本 | **ICU 78**,单一数据对象 `icudt78l_dat.o` | `ar t libicudata.a` / `strings` |
| 全量 locale | data 内含 `af.res` `af_NA.res` `af_ZA.res` `agq.res` … | `strings libicudata.a` |

静态链接的 `libicudata.a` 就是整份 `icudt78l`(约 700 个 locale + coll/brkitr/curr/rbnf/region/unit/zone 全套),`en_tts`/`zh_tts` 各静态塞一份。这与既有分析一致:`.rodata` ≈ ICU 数据 ≈ 89% 体积,`.text` 仅约 3 MB(该 `size -A` 分段数据来自既有分析;本机无 ELF 读取工具 `size/readelf/llvm-*` 支持 aarch64,未复测)。

## 2. ICU 调用面(本机 grep 全量确认 —— 这是裁剪 filter 的依据)

跨 `tts_normalizer_engine.{cpp,hpp}`、`lits_tn_jni.cpp`、`lits_tn_inprocess.cpp`、`ru_year_spellout.cpp` 全量检索:

**TN 真正用到的 ICU 服务(仅 4 类):**

| 服务 | 头文件 | 用法 | 依赖的 ICU 数据 |
|---|---|---|---|
| `RuleBasedNumberFormat(URBNF_SPELLOUT)` | `unicode/rbnf.h` | 数字→读音;`%spellout-cardinal` / `%spellout-numbering` / `%spellout-ordinal` | **rbnf_tree**:`en`、`zh`、`root` |
| `RegexPattern` / `RegexMatcher` | `unicode/regex.h` | 规则管线正则 | 核心 `uprops/ucase/nfc`(在 icuuc,非 locale data) |
| `UnicodeString` | `unicode/unistr.h` | 字符串 | 核心 |
| `Locale` | `unicode/locid.h` | 仅 `Locale::getEnglish()` 与 `Locale::getChinese()` | `locales_tree`:`en`、`zh`、`root` |

**证实完全未使用**(可整树丢弃):`Collator`/`ucol_`、`BreakIterator`/`ubrk_`、`DateFormat`/`Calendar`/`udat_`/`ucal_`、`Currency`/`ucurr_`、`Transliterator`/`utrans_`、`MeasureFormat`/units、region/lang/zone 树、以及 en/zh/root 之外的全部 locale。(grep 结果:上述符号在 TN 源中 0 命中,`Locale::get*()` 仅 English/Chinese 两种。)

locale 硬编码只有 en、zh,与既有结论吻合。

## 3. 头号杠杆:ICU 数据裁剪(预计 31.6 MB → 约 1–3 MB)

### filter 规格 — `scripts/icu_tn_data_filter.json`

保留 `rbnf_tree` + `locales_tree` + `misc`,`localeFilter` 只含 `en`/`zh`(root 由 ICU 自动保留为回退);其余 coll / brkitr / curr / unit / zone / region / lang / translit / conversion 全部 `exclude`。核心 `uprops/ucase/nfc`(regex 依赖)由 ICU 默认保留,体积仅数百 KB。

> 遵循任务「宁可先多留、验证通过后再收紧」:此 filter 起点偏保守(保 `misc` 与整个 `locales_tree` 的 en/zh),回归门绿了之后再逐树收紧。

### 落地路径 — `scripts/build_slim_icu_data.sh`(两条路,择一)

- **Path A(推荐,ICU 原生机制)**:用 ICU 78 源 + `ICU_DATA_FILTER_FILE=scripts/icu_tn_data_filter.json` 重建数据(host 先建工具,再 `--with-cross-build` 交叉出 aarch64-linux-ohos 的静态 `libicudata.a`)。
- **Path B(不重建源)**:从现成 `icudt78l.dat` 用 `icupkg -r <removelist>` 删子集,再 `pkgdata -m static` 用 OHOS 交叉汇编器重打包。remove-list 必须穷尽,保住 root/en/zh 的 rbnf 与核心 uprops/ucase/nfc。

两条路都需要 **OHOS Native SDK** 产出目标架构的 `libicudata.a`。产出后:

```bash
SLIM_ICU_LIB_DIR=<slim>/lib OHOS_NATIVE_SDK=<sdk> scripts/build_dingqiao_harmony_tn.sh
```

`build_dingqiao_harmony_tn.sh` 已加 `SLIM_ICU_LIB_DIR` 覆盖点(未设时与改动前逐字节等价,见 §6)。

### 预计体积(仅估算,未实测)

| | 优化前 | 优化后(预计) |
|---|---|---|
| ICU 数据 | 31.6 MB | ~1–3 MB |
| 单个二进制(text 3 MB + slim data + 其它段) | ~36 MB | ~5–8 MB |

## 4. 次级杠杆(头号验证通过后再评估,本方案未做)

1. **消除 en/zh 重复**:两个二进制内嵌同一份 slim ICU → 合并为单个 `tts` 二进制(参数选语言),或把 slim ICU 做成外置 `.dat` 由两者共享。再省约一半。
2. **构建瘦身**:`-Os`、`-ffunction-sections -fdata-sections` + `-Wl,--gc-sections`、LTO(相对 ICU 是小头;已 strip)。

均为可选、零回退,列为后续。

## 5. 零回退验证门(**必须在合入前执行,本机无法执行**)

1. **TN 输出逐字节一致**:优化前/后二进制喂入全部回归用例,归一化文本 `diff` 必须为空。用例:
   - `tts/android/testdata/dingqiao_batch_cases/android_v3_sdk_stability_1000_cases_improved.jsonl`(1000 条)
   - `tts/android/sdk/src/androidTest/assets/pronunciation-golden-*.jsonl`、`error_pinyin_pronunciation_reviewed.jsonl`(若为发音 golden 而非纯 TN,另取 TN 层用例)
   - 自造覆盖 spellout 的用例:数字 / 金额 / 日期 / 时间 / 序数 / 小数 / 电话 / 年份(en + zh 各一组),确保裁掉的 ICU 数据不影响任何一类。
2. **延迟不回退**:同批用例测 TN 单次耗时,优化前后不得变慢。
3. **产物可用**:slim `en_tts`/`zh_tts` 能启动、加载、跑通用例(不是只看体积)。

**任一 spellout 用例挂掉 = 失败,回滚。**

## 6. 本分支改动清单

| 文件 | 改动 | 是否影响默认行为 |
|---|---|---|
| `scripts/icu_tn_data_filter.json` | 新增:ICU data filter 规格 | 否(仅当被 §3 构建引用) |
| `scripts/build_slim_icu_data.sh` | 新增:slim ICU 构建助手(两条路,含 SDK/工具缺失时的显式报错退出) | 否 |
| `scripts/build_dingqiao_harmony_tn.sh` | 改:引入 `ICU_LIB_DIR=${SLIM_ICU_LIB_DIR:-$OHOS_ICU_ROOT/lib}`,check 与 `-L` 改用之 | **否 —— 未设 `SLIM_ICU_LIB_DIR` 时逐字符等价于原脚本**(`bash -n` 通过) |
| `TN_SIZE_OPT_REPORT.md` | 新增:本报告 | 否 |

未改:TN 规则 / 逻辑 / `rules_v2`;模型 / vocoder / ASR / 其它 SDK;交付二进制。

## 7. 阻塞项(合入前需补齐)

1. **OHOS Native SDK 缺失**(`OHOS_NATIVE_SDK` 未设,无 `aarch64-unknown-linux-ohos-clang++`)→ 无法编译/重链。
2. **ICU 工具 / 源缺失**(无 `icupkg`/`pkgdata`/`genrb`,无 ICU 78 源与独立 `.dat`)→ 无法裁剪数据。
3. **TN 源子模块未初始化**:`dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/`(私有库,SSH)为空,构建脚本编译的 `en.cpp`/`zh.cpp`/`TN_ROOT` 引擎源不可得。
4. **无 aarch64 运行环境**(无设备/emulator/`qemu-aarch64`+`linker64`)→ §5 验证门无法执行。

补齐 1–4 后,即可:复现基线 → `build_slim_icu_data.sh` 产 slim ICU → `SLIM_ICU_LIB_DIR=… build_dingqiao_harmony_tn.sh` 重链 → 跑 §5 → 出实测体积/延迟/diff 结果。
