# ASR License 工具兼容入口

通用离线 license 工具已迁移到仓库根目录：

```text
tools/license/
```

这里保留 `gen_keypair.py`、`issue_license.py`、`verify_license.py`、`selftest.sh` 作为旧路径兼容入口，实际执行 `tools/license/` 下的共享实现。新增签发流程和文档请使用：

```bash
cd tools/license
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python issue_license.py --features ASR,TTS ...
```

鼎桥 Demo / 客户专用包装脚本仍保留在本目录：

```bash
bash asr/tools/license/issue_dingqiao_demo.sh
bash asr/tools/license/issue_dingqiao_customer.sh
```

详细说明见 `../../../tools/license/README.md`。
