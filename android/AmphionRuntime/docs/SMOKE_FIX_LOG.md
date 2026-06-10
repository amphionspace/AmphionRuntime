# 鼎桥 Demo 真机 Smoke 修复记录

> 三星真机口播 10 条（2026-06）。用户反馈整体良好、有个别小错误；  
> 因 Demo 无导出，以下 ASR 误识来自口播常见模式 + `DingqiaoSmokeReplayTest` 回放定位。

## 用例与修复

| # | 场景 | 口播句 | 典型 ASR 误识 | 期望 Final | 修复 |
|---|------|--------|---------------|------------|------|
| 1 | 术语 | 巡逻组已签收**订单**… | `巡逻组已签收。 正在前往…`（截断） | 签收警单 | `term_homophones.csv` 增补 |
| 4 | 术语 | 暂不需要**增派**… | `暂不需要增派，`（逗号截断，非句号） | 增派警力 | `term_homophones.csv` 增补 |
| 6 | 车牌 | 辽 B **八八四九** | `辽B八八四九`（漏一位八→8849） | 辽B88849 | `PlateNormalizer` 锚点规则 |
| 其余 | — | 见 smoke 清单 | 回放已通过 | — | 无需改动 |

## 回归

```bash
cd android/AmphionRuntime
./gradlew :sdk-police:testDebugUnitTest --tests "com.amphion.police.DingqiaoSmokeReplayTest"
./gradlew :sdk-police:testDebugUnitTest
```

修复后请重装 Demo spot-check #1、#4、#6。

## 待补（需真机 Final 原文）

若 spot-check 仍有失败，请把 **ASR 原文（partial/final 均可）→ 实际 Final → 期望** 补到本表，并追加 `term_homophones.csv` / `station_homophones.csv` / `PlateNormalizer` 规则。
