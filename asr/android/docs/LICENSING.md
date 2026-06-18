# Amphion SDK 商用授权方案（离线装机 License）

适用 SDK 版本：0.2.x 起。

本文是内部文档，覆盖三件事：行业做法调研、我方授权方案与技术设计、防破解边界与商业模式建议。给业务方看的接入说明在 INTEGRATION.md，交付与计费 SOP 在 DELIVERY.md。第一次接触本套授权、想先弄懂原理与操作的同事，建议先读 LICENSE_EXPLAINED.md（对内扫盲，大白话讲清原理 / 怎么鉴权 / 怎么防泄漏）。

## 1. 一句话结论

端侧 ASR SDK 走纯离线装机 License：我方用私钥签发 `.lic`（绑定 applicationId + 签名证书 + 到期 + 装机档位 + 功能模块），SDK 内置公钥离线验签，全程零网络。装机量按合同档位 + 抽样审计计，不实时联网计量；如需离线硬上限，走 Phase 2 批量激活码（见 §7）。

## 2. 行业调研

### 2.1 科大讯飞离线 SDK（最直接对标「装机量」）

讯飞有两套并存的机制：

老 MSC SDK（SpeechUtility.createUtility）：appid + 包名强绑定，SDK 静态库与 appid 一一对应，对不上报 10407 错误。

新 AIkit 离线 SDK（两个正交维度）：

| 维度 | 取值 | 说明 |
| --- | --- | --- |
| 授权方式 | 设备授权（authType=0） | 按设备数+有效期；采集 android id/mac/imei 按权重算法生成设备指纹，激活满额拒绝新设备，计量准确 |
| 授权方式 | 应用授权（authType=1） | 绑定 applicationId，不限台数，可限有效期；需提供应用唯一标识 |
| 激活方式 | 在线激活 | 首启联网拿 license 缓存本地，之后离线可用；清缓存/恢复出厂需重新联网激活 |
| 激活方式 | 离线激活（装机量>1万） | 预签批量激活文件内置设备，初始化指定路径，SDK 解析激活，激活后文件自动删除 |

其他要点：能力按 ability ID 分别授权；非永久离线激活文件有效期 3 天（错误码 18008）；隐私上要求在隐私政策声明采集 android ID。

讯飞离线语音合成的装机量统计口径与阶梯定价（公开资料）：

| 档位 | 价格 | 装机量 | 单机成本 |
| --- | --- | --- | --- |
| 体验版 | 免费 | 10（90天试用） | 0 |
| 基础包 | 8000 元 | 2000 | 4.00 元 |
| 中级包 | 17500 元 | 5000 | 3.50 元 |
| 高级包 | 30000 元 | 10000 | 3.00 元 |
| 豪华包 | 125000 元 | 50000 | 2.50 元 |

装机量统计：在终端设备安装应用并启用离线引擎记 1 个；同一设备卸载重装不重复计；Android 按 android id/mac/imei/系统信息统计，任一参数变化记 1 个。发音人库与装机量是两项独立授权，固定授权价、配合装机量使用。

### 2.2 Picovoice（端侧语音，海外对标）

每个 app 一个 AccessKey 初始化；运行时全离线（HIPAA/GDPR 友好），但 licensing 与 usage tracking 仍需偶尔联网。商业模式按 per-device fixed licensing（而非 per-API-call）+ 订阅分层（free 到 enterprise），规模越大边际成本越低。

### 2.3 腾讯音视频终端 SDK（License 绑定对标）

正式 License 移动端仅按 Bundle ID / Package Name 绑定；单 license 不跨端（移动端与 PC 端需分别购买）；按年付费，到期前通过站内信/邮件/短信提醒续期。

### 2.4 定价模式光谱（综合）

| 模式 | 适用 | 特点 |
| --- | --- | --- |
| 买断 | 长期稳定、单产品 | 一次性永久授权，成本可预测 |
| 订阅 | 需持续更新 | 年费/月费含版本更新，到期续费 |
| 装机量/DAU 阶梯 | B2B 规模化 | 量越大单价越低 |
| 功能模块点菜 | 能力差异化 | 核心功能独立定价、按需组合 |
| 私有化部署 | 数据敏感大客户 | 前期投入高、边际成本趋零 |

## 3. 我方方案选型与推导（第一性原理）

### 3.1 为什么纯离线，而不是在线激活计量

不可违背的约束：本 SDK 的核心卖点之一是零网络、不发任何网络请求。在线激活计量需要 INTERNET 权限 + 自建高可用 server + 采集设备标识，直接侵蚀这个卖点与隐私优势，且目标客户（智能硬件/对讲机类，有 `:samples:mini-demo` 240x320 变体佐证）设备未必有稳定网络。注意：`:samples:public-demo` 为演示云端 ASR 入口保留 INTERNET 权限，但 SDK 本身和离线鉴权链路不联网。

结论：默认纯离线授权。代价是装机量不实时实测，靠合同档位 + 抽样审计；防破解有固有上限（见 §5）。

### 3.2 为什么 ECDSA P-256，而不是 Ed25519 / RSA

SDK minSdk 24。Ed25519 的 java.security 支持需 API 33，覆盖不了 24；RSA-2048 可用但签名/公钥更大。ECDSA P-256（SHA256withECDSA）在 API 24 全覆盖、签名与公钥都短，是唯一同时满足「全版本 + 现代 + 紧凑」的选择。已用 java.security 与 Python cryptography 实测互通（见 asr/tools/license/selftest.sh 与跨端验签）。

### 3.3 为什么应用级授权，而不是讯飞式设备指纹

讯飞「计量准确」建立在采集 android id/mac/imei 拼设备指纹 + 联网激活之上。我方为守住零网络与隐私干净两个卖点，本轮只做应用级离线授权：只读宿主本机签名证书做比对，不采集任何设备标识。按设备硬计量留作 Phase 2 选项（§7）。

### 3.4 「装机量」在离线方案下的真实含义

离线无服务器仲裁，无法实时统计真实装机数。因此本轮 installTier 是声明性档位：写进 license 供展示/审计，实际约束靠合同 + 抽样审计。这是离线路线的逻辑必然，不是实现妥协。

## 4. 技术设计

### 4.1 .lic 文件格式

信封（UTF-8 JSON）：

```
{"payload_b64": "<base64(UTF-8 JSON of claims)>",
 "alg": "SHA256withECDSA",
 "sig_b64": "<base64(DER ECDSA-P256 signature over the decoded payload bytes)>"}
```

签名覆盖的是 payload 解码后的原始字节，验签端不重新序列化，从根上规避 canonical JSON 歧义（这是 Python 签发与 Kotlin 验签逐字节一致的关键）。

payload claims 字段见 asr/tools/license/README.md §5。

### 4.2 验签与绑定校验流程

SDK 端 LicenseVerifier（internal）在 AmphionRuntime.init 内执行：

1. 公钥为空（构建期未注入）→ DEV_UNLICENSED，跳过一切校验（开发/内部构建）。
2. license 缺失 → 6001。
3. 信封/payload 解析失败 → 6002。
4. ECDSA 验签失败 → 6003。
5. applicationId != 宿主 packageName → 6004。
6. certSha256 非空且与宿主签名证书不符 → 6005。
7. expiresAt 非空且超出（到期日当天有效 + 宽限天数）→ 6006。
8. 全过 → LICENSED。

### 4.3 失败策略

AmphionOptions.licenseEnforcement：

| 取值 | init 行为 |
| --- | --- |
| ENFORCE（默认） | 校验失败抛 IllegalStateException(code=6xxx)，fail-fast |
| PERMISSIVE | 不抛，仅打 ERROR 日志，licenseStatus().state=INVALID，由业务方决定降级/提示 |

到期校验提供 expiryGraceDays 宽限，规避客户端时钟误差误伤。

### 4.4 公钥分发

公钥（base64 of X.509 SubjectPublicKeyInfo DER）经 gradle.properties 的 AMPHION_LICENSE_PUBLIC_KEY 在构建期注入 BuildConfig。空 = 不武装（开发/内部构建不校验）；正式交付构建必须注入真实公钥。私钥永不进库（.gitignore 已忽略）。

## 5. 防破解边界（诚实，分层不过度工程）

固有上限：离线 + 客户端内置公钥验签，逆向者可 patch 验签逻辑或替换内置公钥。这是物理必然，离线方案无法根除，只能抬高门槛 + 法务兜底。

分层措施：

| 层级 | 措施 | 状态 |
| --- | --- | --- |
| 编译 | release 开启 R8 混淆，internal 验签逻辑在交付 AAR 中被混淆 | 本轮已做 |
| 设计 | 验签结果与运行链路耦合，不暴露单一 boolean 开关 | 本轮已做 |
| native | 关键验签下沉到 .so，逆向成本数量级提升 | Phase 2 |
| 法务 | 授权条款禁止反编译/二次授权 + 抽样审计 | 合同侧 |

开启 R8 是相对此前 isMinifyEnabled=false（验签裸奔）的最大改进，但改动后必须用 :samples:public-demo:assembleRelease + 真机回归（见 DELIVERY.md）。

## 6. 商业模式建议

计费单位：装机 License（按 applicationId 授权 + 装机量档位）。

定价结构建议：基础授权（绑定一个 applicationId）+ 装机量阶梯档位（如 ≤1万 / ≤10万 / ≤100万 / 不限）+ 可选功能模块（粤英包、目标说话人声纹、热词）+ 订阅（年费含模型更新）与 买断 二选一。可参考讯飞档位（§2.1）做单机成本随量递减的定价曲线。

功能模块与 license features 字段对应：

| feature | 能力 |
| --- | --- |
| ASR_ZH_EN | 中英 ASR |
| ASR_YUE_EN | 粤英 ASR |
| TARGET_SPEAKER | 目标说话人声纹 |
| HOTWORDS | 热词增强 |

注意：本轮 features 仅写进 license 供展示/审计，SDK 尚未按 feature 做能力闸门（运行时不拦截未授权能力）。若要按模块收费并强制，需在 EngineImpl/AsrConfig 接入 feature gating（后续项）。

## 7. 演进路线

| 阶段 | 内容 | 触发条件 |
| --- | --- | --- |
| Phase 2 | 离线批量激活码（对标讯飞离线激活）：预签 N 个一次性激活额度 + 本机设备指纹消耗，离线硬限装机量 | 客户要求按设备硬计量 |
| Phase 2 | feature gating：SDK 按 license.features 拦截未授权能力 | 按功能模块收费并强制 |
| Phase 2 | native 验签下沉 .so | 防破解要求提高 |
| Phase 3 | hybrid/online 计量：可选弱上报做结算对账 | 需要精确实时计量 |
| 跨端 | iOS 端对齐（同构复制 LicenseVerifier） | iOS 商用 |

.lic 已预留 licenseId/installTier 字段，上述演进均不需改文件格式。
