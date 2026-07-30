# License 签发与交付方案的业界实践核对

调研日期：2026-07-30

> 状态：架构评估，不代表合规认证。本文只引用标准组织、监管机构和规范项目的
> 原始资料；SLSA、in-toto 与 IETF SUIT 原本面向软件供应链或固件更新，本文仅将
> 其中的签名、来源证明和防回退原则类比到离线 License，不声称当前方案符合这些规范。

> v1 实施边界：当前私钥、私钥位置、SDK 信任锚和签名算法均不能调整；也不修改 SDK。
> 因此下文的密钥轮换、独立 attestation 签名、强制双人控制、WORM 审计和设备端防回退
> 只作为剩余风险与后续方向，不是 `license_delivery.py` 的验收项。

## 1. 结论

现有 [`license-delivery-governance.md`](license-delivery-governance.md) 是一个良好的
工程治理基线，但还不能笼统称为“业界最佳实践”。它已经抓住了显式授权策略、输入
摘要、设备集合身份、职责划分、最终 ZIP 验收、追加式登记和离线吊销边界等关键问题；
这些方向与 NIST、SLSA、in-toto 和 IETF 的原则一致。

当前有三个高优先级差距：

1. 生产签名仍允许以普通 PEM 文件为第一阶段方案，并把 HSM/KMS 推迟到出现第二个
   签名实现之后；这由代码抽象需求驱动，不是由密钥风险驱动。生产密钥应先建立隔离
   保管、使用审计、cryptoperiod、轮换、泄露响应和信任锚迁移机制。
2. `SHA256SUMS.txt`、未签名的 manifest 和追加式登记簿能发现部分错误，但不能单独证明
   “谁批准、谁验收、记录是否被替换”。审批计划、最终产物摘要和验收结果需要有可验证
   的身份绑定及防篡改保护。
3. 方案正确承认离线旧 License 不能远程吊销，但尚无设备端防回退。若产品要承诺
   supersede/revoke 在设备上生效，必须增加单调 generation、可信持久状态和旧版本拒绝
   规则；只签发完整快照不能阻止重新安装旧 License。

风险等级：高。签名密钥一旦泄露，影响面是所有信任该公钥的 SDK；离线 License 一旦
进入现场，也无法依靠服务端补救。

## 2. 逐项核对

| 领域 | 现有方案判断 | 标准依据与差距 | 建议 |
| --- | --- | --- | --- |
| 生产密钥保管与轮换 | 部分符合 | NIST SP 800-57 要求按完整生命周期管理密钥、设置 cryptoperiod、保护存储并在周期结束前准备替代密钥；IETF RFC 9124 第 4.3.17、4.3.18 节建议签名密钥与联网设备隔离，例如 HSM 或隔离主机，并定期更换委派签名密钥。普通目录中的 PEM 本身不能提供这些保证。 | 阶段一就定义生产密钥策略；优先使用 HSM/KMS 或受控隔离签名机，禁止私钥导出。建立 key ID、公钥指纹、状态、cryptoperiod、使用审计、备份/恢复、泄露处置和 SDK 信任锚轮换演练。HSM 与隔离签名机二选一是风险和运营条件决定的，不要求先出现两个代码适配器。 |
| 职责分离与审批 | 方向正确，执行偏弱 | NIST SP 800-53 AC-5 要求识别必须分离的职责，并用访问授权支持这种分离。现有四角色模型合理，但“同一人可承担多个角色”且登记即可，会让控制停留在文档层。 | 明确定义生产签发的不可兼任矩阵，并由系统权限执行。至少让申请/批准与生产签名不可由同一身份无痕完成；是否每次都双人批准应由风险分级决定。永久授权、大范围设备变更和信任策略变更应强制双人批准。 |
| 不可变请求与产物来源 | 基线较好，缺少防篡改身份绑定 | SLSA Source L2 将连续、不可变、保留的历史和同时生成的防篡改来源证明视为可靠归因基础；NIST SP 800-53 AU-9、AU-10 分别要求保护审计信息并为指定动作提供可归因证据。仅保存 Git commit、摘要和人员姓名不能证明记录未被有权限者改写。 | 将已批准 request、源摘要、规范化规则、SN 集合身份、工具版本、License 摘要和验证策略串成一条内容寻址记录；审批、签发和验收事件由组织身份签名或写入具备不可变版本/WORM 能力的审计存储。不要把“追加式 JSON/数据库表”直接等同于不可变。 |
| 签名 manifest / attestation 与普通 checksum | 存在明显差距 | SHA-256 只给出完整性比对；如果攻击者能同时替换文件和 checksum，就没有来源认证。in-toto Attestation Framework 用 Statement 的 subject digest 把声明绑定到具体产物，并用 Envelope 签名认证声明；SLSA VSA 还要求验证签名以及 subject 是否匹配实际产物。 | 保留 `SHA256SUMS.txt` 作为便捷校验，同时增加签名的交付 attestation。它应绑定最终 ZIP 摘要、内部文件摘要、已批准策略摘要、`licenseId`、`snSetId`、签发 key ID、验证器身份和验证策略版本。签名密钥可与 License 内容签名密钥分离，缩小权限和轮换失败域。 |
| 设备标识符与伪名化 | 默认不交付明文是正确方向；哈希边界需说清 | NIST SP 800-122 强调 PII 判断和保护应结合具体上下文；设备 SN 是否属于个人信息取决于它能否关联到自然人。GDPR 第 5 条体现目的限制、数据最小化和保存期限原则。ICO 的官方伪名化指南指出，无额外秘密的确定性哈希可能遭受枚举、字典和猜测攻击，伪名化数据也不等于匿名数据。 | 把明文 SN、License 内设备哈希、集合摘要和来源文件摘要都按敏感标识符分级；仅在必要系统和必要期限内保留。不要把 `SHA-256(SN)` 宣称为匿名化。外部报告优先使用不直接暴露集合摘要的随机 `snSetId`；内部若需要稳定匹配，可评估带密钥摘要或随机 token，但不能把新秘密硬编码进 SDK。运行时设备绑定所需的现有哈希仍应按敏感数据保护。 |
| 完整快照与增量 | 合理，但属于场景选择 | 没有通用标准要求离线 entitlement 必须使用完整快照。RFC 9124 允许差分 payload，但要求认证 precursor digest，说明增量只要显式绑定基线也可以安全。完整快照的优势是单文件自包含、恢复简单；代价是体积和签发成本。 | 当前设备量和 License 解析性能可接受时继续完整快照。若未来采用 delta，必须签名绑定 `baseLicenseDigest`、generation、增删集合与合成后集合摘要，并从可信基线原子应用。无论 full 还是 delta，都不能替代设备端 anti-rollback。 |
| 最终包验证 | 高度符合 | SLSA 的 artifact verification 要求验证 attestation 签名、subject digest 和预期策略；RFC 9124 第 4.3.19 节要求部署前验证 manifest。以最终 ZIP 为唯一输入重新解压和验收，正好避免验证中间产物后又重新打包的状态错位。 | 保留 zip-only 门禁；把验证器版本、策略摘要、输入 ZIP 摘要和结果签进 attestation。高风险批次由与签发环境分离的验证环境或验证身份执行。 |
| 审计与留存 | 方向正确，制度未闭合 | NIST SP 800-53 AU-9 要求防止审计记录被未授权访问、修改和删除；AU-11 的留存期由组织按记录政策、调查和法规需要明确。现有“由合同和公司策略决定”是正确边界，但尚缺可执行的期限表和删除证据。 | 为 request、原始 SN、规范化集合、批准记录、正式 License、交付包、attestation 和临时文件分别定义保留期、访问角色、legal hold、备份恢复和到期销毁。审计记录与被审计的签发环境分离保存，并定期验证可读取性。 |
| 离线吊销与防回退 | 已正确识别限制，尚未解决 | RFC 9124 第 3.2、4.3.1 节要求 manifest 携带单调递增序号，设备拒绝小于本地已接受值的 manifest；第 4.3.3 节说明过期机制依赖可信时钟。管理系统中的 `REVOKED` 状态不会自动改变离线设备。 | 若业务要求旧 License 失效，在 SDK 安全存储中持久化最高 `licenseGeneration` 并拒绝更低值；同时设计恢复出厂、数据回滚、换机、灾难恢复和紧急回退授权。若没有可信时钟和更新介质，就不能承诺即时吊销；永久 License 尤其如此。 |

## 3. 通用控制与场景选择

以下原则不依赖团队规模或 License 文件格式，应该视为生产系统的通用控制：

- 私钥最小暴露、隔离保管、可审计使用、明确生命周期和泄露响应；
- 对高风险动作实施最小权限、可归因审批和必要的职责分离；
- 用签名把授权意图、确切输入、确切产物和验证结果绑定起来；
- 消费前同时验证签名、产物摘要、签发身份和业务策略，而不只核对 checksum；
- 对 SN 和其衍生标识符做数据分类、访问限制、最小化和期限管理；
- 审计记录防篡改、可检索，并有明确保留与销毁政策；
- 如果声称“新 License 替代旧 License”，设备端必须有可执行的防回退状态。

以下是上下文相关的工程选择，不能简单贴上“最佳实践”标签：

- 选 HSM、云 KMS 还是隔离签名机；
- 一次签发需要两人还是更多人、哪些角色可兼任；
- 使用完整快照还是带可信基线的 delta；
- 是否向客户单独交付明文 SN 清单；
- 每类记录具体保留多少年；
- 采用在线吊销、定期离线更新、到期时间还是永久授权。

## 4. 推荐落地顺序

1. 先补密钥管理和信任锚轮换设计，不再以“尚无第二种 signer 实现”为推迟依据。
2. 将 `PlanReceipt`、`IssuanceReceipt`、`VerificationReceipt` 统一为可签名、内容寻址的
   attestation，并由最终 ZIP 摘要串联。
3. 用权限系统强制生产审批与签名职责边界，把所有例外作为有身份、有期限的审计事件。
4. 建立数据分类和保留期限表，明确普通 SHA-256 设备哈希不是匿名化保证。
5. 只有业务明确要求离线替换/吊销时，再实现 `licenseGeneration` 和安全持久化；否则继续
   对外明确“管理状态不等于现场失效”。

主要取舍：以上措施会增加签发准备、密钥运维和现场状态恢复复杂度，但它们处理的是私钥
泄露、批准记录被改写和旧授权回退这三个高影响失败域。完整快照和当前 zip-only 验收可以
保留，不需要为了追求标准化而改写现有 License claims。

## 5. 原始资料

- [NIST SP 800-57 Part 1 Rev. 5：Recommendation for Key Management](https://doi.org/10.6028/NIST.SP.800-57pt1r5)
- [NIST SP 800-53 Rev. 5：AC-5、AU-9、AU-10、AU-11](https://doi.org/10.6028/NIST.SP.800-53r5)
- [NIST SP 800-122：Guide to Protecting the Confidentiality of PII](https://doi.org/10.6028/NIST.SP.800-122)
- [SLSA v1.2：Source Requirements](https://slsa.dev/spec/v1.2/source-requirements)
- [SLSA v1.2：Verifying Artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts)
- [SLSA v1.2：Verification Summary Attestation](https://slsa.dev/spec/v1.2/verification_summary)
- [in-toto Attestation Framework：Statement](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
- [in-toto Attestation Framework：Envelope](https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md)
- [IETF RFC 9124：A Manifest Information Model for Firmware Updates in IoT Devices](https://datatracker.ietf.org/doc/rfc9124/)
- [GDPR：Article 5, Principles Relating to Processing of Personal Data](https://eur-lex.europa.eu/eli/reg/2016/679/art_5/oj)
- [UK ICO：Pseudonymisation Guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/anonymisation/pseudonymisation/)
