# Git 外资产同步

模型、测试语料等不适合进入 Git 的协作输入统一存放在华为云 OBS。清单固定对象路径、大小、
整包 SHA-256 和逐文件 SHA-256；干净检出可以恢复出与发布构建机相同的输入。

## 首次配置

凭据只通过本机环境变量提供，禁止写入仓库：

```bash
export OBS_AccesskeyID=...
export OBS_SecretAccesskey=...
export OBS_Endpoint=https://obs.example.com
python3 -m pip install esdk-obs-python
```

## 跨机恢复

```bash
python3 tools/assets/sync.py list
python3 tools/assets/sync.py remote-verify all
python3 tools/assets/sync.py fetch all
python3 tools/assets/sync.py verify all
```

仓库模型恢复到清单声明的 Git 忽略目录。测试语料默认恢复到
`~/.cache/amphion-runtime/test-data/v1`；可用 `AMPHION_TEST_DATA_DIR` 指定共享磁盘。
中断的分片下载保存在 `~/.cache/amphion-runtime/assets`，可用
`AMPHION_ASSET_CACHE_DIR` 改位置。

当前 canonical 受限资产是 `team-secure-state-v5`，包含团队授权根、可跨机签名配置、DevEco 解密材料、
完整签名材料和设备清单；该版本已通过 Harmony 真机构建、安装和 SDK smoke。新机器按需执行
`python3 tools/assets/sync.py fetch team-secure-state-v5`。v2-v4 仅作为不可变历史快照保留，不应用于新环境。
对象使用 OBS SSE-KMS；拥有同一
OBS/KMS 权限的团队成员下载时会透明解密。恢复采用合并模式，不删除 `.secure` 下其他本地内容，
也不会默认覆盖同名但内容不同的文件；确认要采用远端版本时显式增加 `--replace-existing`。
受限 ZIP 的本地明文临时文件无论成功或失败都会清理，并保留清单声明的 `0600`/`0644` 权限。

TTS 协作输入拆成三个用途明确的 bundle：`tts-checkpoints-v3-20260806` 恢复训练 checkpoint，
`tts-runtime-zhen-v1` 恢复 Android/Harmony 共用的 ONNX 与前端资源，`tts-harmony-tn-v1` 恢复
HarmonyOS arm64 TN 可执行文件。这样新机器可以按训练、导出或真机验证场景只取所需资产。

## 上传与审计

```bash
python3 tools/assets/sync.py audit
python3 tools/assets/sync.py publish asr-zhen-v1
```

`publish` 只接受清单中逐文件身份完全匹配的仓库资产，并使用固定顺序、时间戳和权限构造
可重复 ZIP。对象键包含整包 SHA-256，工具不会覆盖不同内容。受限 bundle 必须经对象级
SSE-KMS 上传，远端校验若看不到 `kms` 标记就失败。

`audit` 对每个 Git 忽略文件作三选一判定：已同步资产、明确排除项、未分类文件。未分类文件
会使命令失败，必须先决定是否新增 bundle；不能用扩大通配符绕过。当前明确排除：

- 构建、IDE、虚拟环境、派生 SDK 模型、报告与交付输出；
- 由 `tts-runtime-zhen-v1` 确定性生成的 Android 外置资源和 Harmony HAR 内置资源副本；
- 可由固定上游地址重建的依赖缓存；
- 未登记的客户数据、个人声纹数据，以及不属于受控 `.secure` bundle 的敏感输入。

新受限文件不会被通配符自动带入对象；必须显式加入清单，避免历史构建副本或个人数据混入。

现有 `asr/test-data/manifest.json` 仍是测试语料的权威清单，并被本工具包含；原有
`asr/tools/test_data.py` 命令保持兼容。
