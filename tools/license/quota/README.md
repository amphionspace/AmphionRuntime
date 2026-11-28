# 按数量离线授权（额度证书链）工具

设计、安全控制与验证结果见 [docs/edge-quota-license.md](../../../docs/edge-quota-license.md)。

| 文件 | 用途 | 谁运行 |
|---|---|---|
| `quota_chain.py` | 格式、严格解析、设备端校验参考实现、日志重放与对账 | 共用库 |
| `vendor_quota.py` | `issue-quota` 签额度证书（底层）；`audit-verify` 对账 | 我方 |
| `quota_delivery.py` | 正式签发门禁 `plan` / `issue` / `verify` / `record` | 我方 |
| `site_issuer.py` | `init` / `install-quota` / `activate` / `activate-batch` / `deactivate` / `audit-export` / `status` | 客户内网签发点 |
| `device_sim.py` | 软件密钥模拟设备（真机用 HUKS / AndroidKeyStore） | 测试 |
| `gen_sdk_fixtures.py` | 生成 SDK 互测用例（临时密钥） | 开发 |
| `test_quota_chain.py` | 正常流程与攻击矩阵 | 开发 |
| `test_quota_delivery.py` | 签发门禁 | 开发 |

```bash
python3 -m venv .venv && .venv/bin/pip install -r ../requirements.txt pytest
.venv/bin/python -m pytest -q .
# 鸿蒙校验核心与 Python 互测（需要 node 22+）
(cd ../../.. && tools/license/quota/.venv/bin/python -m pytest -q asr/tools/tests/test_harmony_quota_chain.py)
# 重新生成安卓互测用例后跑 JVM 单测
.venv/bin/python gen_sdk_fixtures.py --out ../../../asr/android/sdk/src/test/resources/quota-chain/fixtures.json
(cd ../../../asr/android && ./gradlew :sdk:testDebugUnitTest --tests 'com.amphion.asr.internal.QuotaChainVerifierTest')
```

签发点口令通过环境变量 `AMPHION_SITE_PASSPHRASE` 传入（至少 12 个字符）。
测试与演练只用临时密钥；不要把 `.secure/` 下的生产私钥用于本目录的测试。
