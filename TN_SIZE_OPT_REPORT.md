# TN 体积优化报告(端侧 TTS 文本归一化 / ICU 数据裁剪)

> 分支:`tn/icu-data-slim-proposal`(基于 `origin/lits_dingqiao_sdk_vocos24k_v3`)
> 状态:**头号杠杆已在 host 上实测并通过零回退门。** ICU 数据 31.57 MB → 2.55 MB(−91.9%),TN 驱动 35.07 MB → 5.82 MB(−83.4%),优化前/后 TN 输出**逐字节一致**(4426 行,en+zh),延迟不回退。
> 尚缺:在 **arm64 / OHOS 交叉工具链**上重建交付二进制并在设备上复跑(本机无 OHOS SDK)。未 push、未改交付产物、未改 TN 规则/rules_v2。

---

## 0. TL;DR

| 指标 | 优化前 | 优化后 | 降幅 |
|---|---|---|---|
| ICU `libicudata.a`(数据) | 31.57 MB | **2.55 MB** | **−91.9%** |
| ICU 数据包条目数 | 4305 | 338 | −92% |
| TN 驱动二进制(host, 静态链接) | 35.07 MB | **5.82 MB** | **−83.4%** |
| 交付 `en_tts`(arm64,实测) | 35.97 MB | **~6.9 MB(推算)** | ~−81% |
| 交付 tn-bin 合计(en+zh 两个) | 71.9 MB | **~13.9 MB(推算)** | ~−81% |
| TN 归一化输出 | — | **逐字节一致(0 回退)** | — |
| TN 单次延迟 | 基线 | 持平(略快) | 0 |

## 1. 根因(已证实)

交付二进制静态链接整份 **ICU 78.1** `icudt78l`(`libicudata.a` 33,108,176 B,与交付 33,108,140 B 仅差 36 B → host 上 vanilla 78.1 数据≈交付所用数据),含 ~700 个 locale + coll/brkitr/curr/rbnf/region/unit/zone 全套。`en_tts`/`zh_tts` 各静态塞一份。`.rodata` ≈ ICU ≈ 89% 体积,`.text` 仅约 3 MB。

## 2. ICU 调用面(全量 grep 确认 → 裁剪依据)

TN 引擎(`tts_normalizer_engine`)+ 语言 main(`en.cpp`/`zh.cpp`)+ JNI + in-process,真正用到的 ICU 服务只有:

- **`RuleBasedNumberFormat(URBNF_SPELLOUT)`** — 数字转读音,locale 硬编码仅 `Locale::getEnglish()`("en")、`Locale::getChinese()`("zh"),用 `%spellout-cardinal/-numbering/-ordinal`;
- **ICU 正则**(`unicode/regex.h`)、`UnicodeString`、`Locale` — 仅依赖核心 uprops/ucase/nfc(在 icuuc,非 locale 数据)。

**完全未用**(可整树丢弃):Collator、BreakIterator、DateFormat/Calendar、Transliterator、MeasureFormat/units、region/lang/zone。

## 3. 裁剪方案与⚠️关键坑

`ICU_DATA_FILTER_FILE` = [`scripts/icu_tn_data_filter.json`](scripts/icu_tn_data_filter.json):`localeFilter` 只留 `en`/`zh`(+root 自动);`featureFilters` 保 `rbnf_tree`+`locales_tree`+`misc`+**`curr_tree`**+`curr_supplemental`,丢弃 coll/brkitr/lang/region/unit/zone/translit/conversion。

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

- **结果:full-ICU 与 slim-ICU 输出逐字节一致,0 回退**(harness:[`scripts/tn_icu_slim/verify_zero_regression.sh`](scripts/tn_icu_slim/verify_zero_regression.sh))。
- **延迟**:稳定性语料 best-of-3,en 3.50→3.48s、zh 7.51→7.50s(持平,未回退)。

**关于 `test/expected/*.golden`**:这些 golden 与当前 `rules_v2` 已**不同步**——即便 full-ICU host 构建也与它们 diff(如 `$3.50` golden="three dollars and fifty cents",当前规则="three point five dollars")。这是子模块里既有的规则-golden 漂移,与本 ICU 优化无关,故**不能用作回归基准**;正确基准是 full-vs-slim 逐字节一致(已通过)。

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

## 7. 交付到设备(剩余步骤,需 OHOS SDK)

`scripts/build_slim_icu_data.sh` 的 host 配方已验证;交付需把其中 `runConfigureICU MacOSX` 换成 OHOS 交叉构建(host 先建工具→`--host=aarch64-linux-ohos --with-cross-build=<hostbuild>` + OHOS clang,`ICU_DATA_FILTER_FILE` 不变),产出 arm64 的 slim `libicudata.a`,再:

```bash
SLIM_ICU_LIB_DIR=<slim>/lib OHOS_NATIVE_SDK=<sdk> scripts/build_dingqiao_harmony_tn.sh
```

`build_dingqiao_harmony_tn.sh` 已加 `SLIM_ICU_LIB_DIR` 覆盖点(未设时与原脚本逐字符等价)。之后在设备/emulator 上跑一遍冒烟,确认 arm64 产物可加载可跑通。

**阻塞**:本机无 OHOS Native SDK(`aarch64-unknown-linux-ohos-clang++`)与 aarch64 运行环境,故仅完成 host 验证。头号杠杆的正确性已由 host 逐字节 diff 证明;host↔target 仅差 vanilla-vs-OHOS-patch 与平台,数据"哪些类未被 RBNF+regex 使用"的结论不随平台变化,风险低,余一次 on-target 复跑确认。

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
