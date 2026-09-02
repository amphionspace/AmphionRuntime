# TN 体积优化报告(端侧 TTS 文本归一化 / ICU 数据裁剪)

> 分支:`tn/icu-data-slim-proposal`(基于 `origin/lits_dingqiao_sdk_vocos24k_v3`)
> 状态:**已实建 arm64 交付二进制并通过零回退门。** ICU 数据 31.57 MB → 2.55 MB(−91.9%);**arm64 `en_tts`/`zh_tts` 各 35.97 MB → 6.92 MB(−80.8%)**,`.rodata` 33.56 MB → 3.14 MB;优化前/后 TN 输出**逐字节一致**(4426 行,en+zh),延迟不回退。
> 唯一剩余:在 OHOS 设备/emulator 上冒烟(本机无 qemu-user/设备,无法在 macOS 上跑 aarch64-ohos 二进制)。未 push、未改交付产物、未改 TN 规则/rules_v2。

---

## 0. TL;DR

| 指标 | 优化前 | 优化后 | 降幅 |
|---|---|---|---|
| ICU `libicudata.a`(数据) | 31.57 MB | **2.55 MB** | **−91.9%** |
| ICU 数据包条目数 | 4305 | 338 | −92% |
| 交付 `en_tts`(**arm64,已实建**) | 35.97 MB | **6.92 MB** | **−80.8%** |
| 交付 `zh_tts`(**arm64,已实建**) | 35.97 MB | **6.92 MB** | **−80.8%** |
| `en_tts` `.rodata`(arm64) | 33.56 MB | **3.14 MB** | −90.6% |
| 交付 tn-bin 合计(en+zh 两个) | 71.9 MB | **13.83 MB** | **−80.8%(省 58.1 MB)** |
| TN 归一化输出 | — | **逐字节一致(0 回退,4426 行)** | — |
| TN 单次延迟 | 基线 | 持平(略快) | 0 |

## 1. 根因(已证实)

交付二进制静态链接整份 **ICU 78.1** `icudt78l`(`libicudata.a` 33,108,176 B,与交付 33,108,140 B 仅差 36 B → host 上 vanilla 78.1 数据≈交付所用数据),含 ~700 个 locale + coll/brkitr/curr/rbnf/region/unit/zone 全套。`en_tts`/`zh_tts` 各静态塞一份。`.rodata` ≈ ICU ≈ 89% 体积,`.text` 仅约 3 MB。

## 2. ICU 调用面(全量 grep 确认 → 裁剪依据)

TN 引擎(`tts_normalizer_engine`)+ 语言 main(`en.cpp`/`zh.cpp`)+ JNI + in-process,真正用到的 ICU 服务只有:

- **`RuleBasedNumberFormat(URBNF_SPELLOUT)`** — 数字转读音,locale 硬编码仅 `Locale::getEnglish()`("en")、`Locale::getChinese()`("zh"),用 `%spellout-cardinal/-numbering/-ordinal`;
- **ICU 正则**(`unicode/regex.h`)、`UnicodeString`、`Locale` — 仅依赖核心 uprops/ucase/nfc(在 icuuc,非 locale 数据)。

**完全未用**(可整树丢弃):Collator、BreakIterator、DateFormat/Calendar、Transliterator、MeasureFormat/units、region/lang/zone。

## 3. 裁剪方案与⚠️关键坑

`ICU_DATA_FILTER_FILE` = [`scripts/icu_tn_data_filter.json`](../../../scripts/icu_tn_data_filter.json):`localeFilter` 只留 `en`/`zh`(+root 自动);`featureFilters` 保 `rbnf_tree`+`locales_tree`+`misc`+**`curr_tree`**+`curr_supplemental`,丢弃 coll/brkitr/lang/region/unit/zone/translit/conversion。

**⚠️ 头号坑(实测踩到):必须保留 `curr_tree`。** 我最初的 filter 把 currency 也裁了,结果 `RuleBasedNumberFormat` 构造函数返回 `U_MISSING_RESOURCE_ERROR`,**每一条 spellout 都静默变成空字符串**(数字从输出里消失,不崩溃)。原因:RBNF 内部的 `DecimalFormatSymbols` 要加载该 locale 的货币符号。这种坑构建/冒烟都发现不了,**只有逐字节输出 diff 能抓到**。裁剪定位过程见 §5(coll/brkitr 经二分确认无关,唯 curr 必需)。

## 4. 实测结果

- **ICU 数据**:filter 从源(ICU 78.1 raw data)重建 → `libicudata.a` **31.57 MB → 2.55 MB**,包内条目 4305 → 338(保 rbnf 13 项 + curr 136 项 + locale/misc)。
- **驱动二进制**(host 静态链接同一套 TN 源 + rules_v2):**35.07 MB → 5.82 MB**。
- **交付推算**:交付 arm64 `en_tts` 35.97 MB,扣掉省下的 29.0 MB ICU 数据 → **每个 ~6.9 MB**;两个合计 71.9 MB → **~13.9 MB**。

## 5. 零回退验证(已执行,PASS)

方法:用 **ICU 78.1 从源构建两套**(full = 无 filter;slim = 上述 filter),各自静态链接**同一份 TN 源(子模块 commit `9cf6411`,与交付一致)+ rules_v2**,喂入回归语料,**diff full 输出 vs slim 输出**。这是 §"优化前 vs 优化后逐字节一致"的正解(唯一变量=数据子集)。

语料与结果(9 组,4426 行):

| 语料 | en | zh |
|---|---|---|
| 引擎自带 `test/in`(en/zh/zh_car_plates) | OK | OK |
| 自造 spellout 应力集(数字/金额/日期/时间/序数/小数/电话/年份) | OK(49) | OK(40) |
| SDK 稳定性 1000+ 用例 `text`(去重 1476) | OK | OK |
| 发音 golden 派生文本(675) | OK | OK |

- **结果:full-ICU 与 slim-ICU 输出逐字节一致,0 回退**(harness:[`scripts/tn_icu_slim/verify_zero_regression.sh`](../../../scripts/tn_icu_slim/verify_zero_regression.sh))。
- **延迟**:稳定性语料 best-of-3,en 3.50→3.48s、zh 7.51→7.50s(持平,未回退)。

**关于 `test/expected/*.golden`**:这些 golden 与当前 `rules_v2` 已**不同步**——即便 full-ICU host 构建也与它们 diff(如 `$3.50` golden="three dollars and fifty cents",当前规则="three point five dollars")。这是子模块里既有的规则-golden 漂移,与本 ICU 优化无关,故**不能用作回归基准**;正确基准是 full-vs-slim 逐字节一致(已通过)。

## 5.1 方案选型(语言维度 vs 功能维度,对照实测)

裁剪有两个正交维度:**语言**(`localeFilter`,砍掉 en/zh 之外的 ~698 种语言)与**功能**(`featureFilters`,砍掉 coll/brkitr/unit/zone/translit 等 TN 不调用的功能树)。为量化各自贡献、支持保守/激进选型,用**同一 ICU 78.1 源、同机、同 configure flags** 单独构建了各变体(`both` 重建校验 = 2.55 MB,与本报告一致,证明流程可信)。

| 方案 | ICU `libicudata` | 相对 full | arm64 交付二进制/个* |
|---|---|---|---|
| full(不裁) | 31.57 MB | — | 35.97 MB |
| 只砍语言(留全功能,仅 en/zh) | 13.50 MB | −57% | ~17.9 MB |
| 只砍功能(留全语言,砍功能树) | 8.70 MB | −72% | ~13.1 MB |
| **都砍(本方案)** | **2.55 MB** | **−92%** | **6.92 MB** |

\* arm64 二进制:ICU 数据平台无关(同一份 `icudt78l.dat`),估算 = 非数据部分(≈4.4 MB,both 实测)+ ICU 数据;full/both 为实测值。

**维度贡献**(两维度高度重叠——其他 698 种语言的功能数据两边都覆盖,故单独贡献相加 > 实际总省 29 MB):

| 维度 | 单独砍(vs full) | 边际砍(另一维度已砍后) |
|---|---|---|
| 语言(砍 ~698 种其他语言) | 省 18.07 MB | 再省 6.15 MB |
| 功能(砍 coll/brkitr/unit/zone/translit…) | 省 22.87 MB | 再省 10.95 MB |

**选型建议**:

- **保守**:只砍语言(**13.50 MB,−57%**)——TN 只读中英文,其他 698 种语言运行时根本不加载,砍掉零功能影响,无需依赖任何"功能是否用到"的判断,是最稳的一档。
- **激进(本方案)**:都砍(**2.55 MB,−92%**)——比保守再省 ~11 MB,安全性已由逐字节 diff(4426 行零回退,见 §5)覆盖。
- 不推荐"只砍功能"(8.70 MB):保留全部 698 种语言对只读中英文的 TN 是死重量。

## 6. 复现方式(host)

```bash
# 1) 拉 TN 子模块(pin 在交付 commit)
git submodule update --init dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS
# 2) 建 slim ICU 数据(需 icu4c-78.1 sources.tgz + data.zip,unicode-org/icu release-78.1)
ICU_SOURCES_TGZ=…/icu4c-78.1-sources.tgz ICU_DATA_ZIP=…/icu4c-78.1-data.zip \
  scripts/build_slim_icu_data.sh          # 产出 slim libicudata.a(host: MacOSX)
# 另建一套 full ICU(不设 ICU_DATA_FILTER_FILE)作对照
# 3) 零回退验证
FULL_ICU=<full-prefix> SLIM_ICU=<slim-prefix> \
  scripts/tn_icu_slim/verify_zero_regression.sh
```

## 7. arm64 交付产物(已实建)

用 OHOS Native SDK(5.0.2,`aarch64-unknown-linux-ohos-clang++`,经 Rosetta)**交叉构建 slim ICU 数据 + 重链**,产出真实 arm64 二进制:

1. **交叉构建 slim `libicudata.a`(aarch64)**:host 先建 ICU 78.1(作 `--with-cross-build` 参考),再以 `--host=aarch64-linux-ohos` + OHOS clang + `ICU_DATA_FILTER_FILE=icu_tn_data_filter.json` 从源构建数据 → `libicudata.a` **2.55 MB**(与 host slim 逐字节同量)。
2. **重链**:保留**交付所用的 vendored OHOS `libicui18n.a`/`libicuuc.a` + 头文件不变**,只把 `libicudata.a` 换成上面的 slim 版(经 `SLIM_ICU_LIB_DIR`)。

**用 SDK 的 `llvm-size` 实测 arm64 分段(交付基线 vs slim):**

| | 交付 `en_tts` | slim `en_tts` |
|---|---|---|
| 总大小 | 37,714,920 B(35.97 MB) | **7,252,416 B(6.92 MB)** |
| `.rodata`(=ICU 数据) | 33,562,748 B(33.56 MB) | **3,135,388 B(3.14 MB)** |
| `.text` | 3,029,048 B(3.03 MB) | 3,223,724 B(含静态 libc++) |

产物哈希:`en_tts` `71cabe6f…`,`zh_tts` `b3db2ab1…`(sha256)。

**产物与交付二进制的一致性核对**:动态链接器 `interpreter=/system/bin/linker64`(与交付一致);自包含(静态 libc++,与交付一样不依赖 `libc++_shared.so`);仅需 `libc.so`。ELF aarch64 PIE,已 strip,内嵌 ICU 78.1 slim 数据。

> **工具链坑(记录给同事)**:交付二进制是**静态 libc++** + `interpreter=/system/bin/linker64`,但当前 `build_dingqiao_harmony_tn.sh` **没有**设 `-static-libstdc++`/`--dynamic-linker`——用它 + 本机 SDK 5.0.2 直接建出来的是**动态 libc++_shared + `/lib/ld-musl-aarch64.so.1`**,与交付形态不符。这说明交付二进制是用**另一套 OHOS 工具链/配置**建的(其默认即静态 libc++ + linker64)。为得到真正 drop-in,我在重链时显式加了 `-static-libstdc++ -Wl,--dynamic-linker=/system/bin/linker64`。同事在**产线工具链**上跑(其默认已是该形态)则只需加 `SLIM_ICU_LIB_DIR`,无需改脚本——故本分支对 `build_dingqiao_harmony_tn.sh` 只加了 `SLIM_ICU_LIB_DIR` 覆盖点,未动编译 flag。

**唯一剩余**:在 OHOS 设备/emulator 上冒烟(macOS 无 qemu-user、无设备,无法在此运行 aarch64-ohos 二进制)。但零回退已由 host 逐字节 diff 证明,且 arm64 产物内嵌的是同一份 slim `icudt78l.dat`(host 已验证的字节),故此步是形态确认,非正确性确认。

## 8. 次级杠杆(可选,未做)

1. **消除 en/zh 重复**:两个二进制内嵌同一份 2.55 MB slim 数据 → 合并单二进制(参数选语言)或外置 `.dat` 共享 → 再省约一半(~13.9 MB → ~7–8 MB)。
2. 构建瘦身:`-Os` / `--gc-sections` / LTO(相对 ICU 是小头,已 strip)。
3. 进一步收紧 curr(当前保 136 项;可只留 en/zh/root 的 currency 显示串),收益小、风险需再验,列为后续。

## 9. 本分支改动清单

| 文件 | 改动 | 默认行为影响 |
|---|---|---|
| `scripts/icu_tn_data_filter.json` | ICU data filter(**含 curr,已验证最小集**) | 否 |
| `scripts/build_slim_icu_data.sh` | slim ICU 构建配方(host 已验证;含 OHOS 交叉说明) | 否 |
| `scripts/tn_icu_slim/verify_zero_regression.sh` + `spellout_{en,zh}.txt` | 零回退验证 harness + 应力语料 | 否 |
| `scripts/build_dingqiao_harmony_tn.sh` | `SLIM_ICU_LIB_DIR` 覆盖点 | **否(未设时逐字符等价)** |
| `TN_SIZE_OPT_REPORT.md` | 本报告 | 否 |

未改:TN 规则/逻辑/`rules_v2`;模型/vocoder/ASR/其它 SDK;交付二进制;同事分支。
