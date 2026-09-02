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

## 上传与审计

```bash
python3 tools/assets/sync.py audit
python3 tools/assets/sync.py publish asr-zhen-v1
```

`publish` 只接受清单中逐文件身份完全匹配的仓库资产，并使用固定顺序、时间戳和权限构造
可重复 ZIP。对象键包含整包 SHA-256，工具不会覆盖不同内容。

`audit` 对每个 Git 忽略文件作三选一判定：已同步资产、明确排除项、未分类文件。未分类文件
会使命令失败，必须先决定是否新增 bundle；不能用扩大通配符绕过。当前明确排除：

- 构建、IDE、虚拟环境、派生 SDK 模型、报告与交付输出；
- 可由固定上游地址重建的依赖缓存；
- 凭据、私钥、签名、license、设备标识、客户数据和个人声纹数据。

最后一类不得上传到协作桶。若确需共享受限数据，必须先确认授权范围、脱敏方式和独立受控存储。

现有 `asr/test-data/manifest.json` 仍是测试语料的权威清单，并被本工具包含；原有
`asr/tools/test_data.py` 命令保持兼容。
