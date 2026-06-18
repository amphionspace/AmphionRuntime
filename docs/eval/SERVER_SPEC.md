# Amphion ASR Eval Collector 服务端规范

本文档是「评估数据收集服务」的契约规范，供云端实施者据此独立编写服务。客户端是 Android sample 中的 eval 模块（com.amphion.asr.sample.eval.upload.HttpUploader），后续接入 iOS 时遵循同一份契约。

文档分为三层：

1. NORMATIVE：协议契约 —— 任何合规实现必须遵守
2. INFORMATIVE：参考实现 —— 推荐方案，可不照搬
3. CONFORMANCE：验收 —— 用 curl 跑通即视为合规

---

## 一、NORMATIVE：协议契约

### 1.1 端点

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /v1/recordings/{recording_id} | 上传一条录音的 audio + meta + 可选 hypothesis |
| GET | /v1/health | 健康检查（可选，建议实现） |

recording_id 是客户端生成的 UUIDv4 字符串，作为幂等键。

### 1.2 鉴权

请求头必带 Authorization: Bearer <token>。

token 由服务端运维侧生成，约定每个 tester 一个独立 token（推荐），或全员共享一个 token（最小化部署）。token 与 tester_id 的映射建议在服务端配置中维护：

服务端必须校验 token 有效性。无效 → 401。若 token 关联了 tester_id 且与请求 body 中 meta.tester_id 不一致 → 403。

### 1.3 请求体

Content-Type: multipart/form-data，至少包含两个 part：

| name | filename | content-type | 必选 | 说明 |
| --- | --- | --- | --- | --- |
| meta | meta.json | application/json | 是 | 完整 meta（schema 见 docs/eval/SCHEMA.md） |
| audio | audio.wav | audio/wav | 是 | 16kHz / 16-bit / mono PCM WAV |
| hypothesis | hypothesis.txt | text/plain | 否 | 设备端 final 文本，UTF-8 |

请求头额外字段：

| Header | 必选 | 说明 |
| --- | --- | --- |
| X-Amphion-Schema-Version | 是 | meta.json 的 schema_version 整数，必须等于 body 内字段 |

### 1.4 幂等性

服务端必须按 recording_id 实现幂等：

- 第一次到达 → 写入磁盘，返回 200 {"status":"stored"}
- 重复到达（同 recording_id）→ 不重复写入，返回 200 {"status":"duplicate"}
- 不允许返回 409；客户端会按 4xx 处理永久失败，导致用户体感卡死

幂等判定的事实源是磁盘目录是否存在，不是数据库。这是为了让单机文件系统就能跑通最小实现。

### 1.5 响应

成功响应（HTTP 200）：

```json
{ "status": "stored", "recording_id": "0bf8...", "received_at": "2026-05-19T10:47:01Z" }
```

或：

```json
{ "status": "duplicate", "recording_id": "0bf8...", "stored_at": "2026-05-19T10:30:00Z" }
```

错误响应（HTTP 4xx / 5xx）：

```json
{ "code": "UNAUTHORIZED", "message": "bearer token invalid or expired" }
```

错误码取值必须用下表枚举值，不可自创。客户端按 code 字段（而不是 HTTP code）决定重试策略。

### 1.6 错误码表

| HTTP | code | 客户端行为 | 说明 |
| --- | --- | --- | --- |
| 200 | （无） | 成功 | status=stored 或 duplicate |
| 400 | SCHEMA_MISMATCH | 永久失败 | meta.json schema_version 不支持 |
| 400 | INVALID_AUDIO | 永久失败 | audio.wav 不是合法 WAV 或非 16kHz / mono / 16-bit |
| 400 | RECORDING_ID_MISMATCH | 永久失败 | URL recording_id 与 body 内字段不一致 |
| 401 | UNAUTHORIZED | 永久失败 | token 无效或过期 |
| 403 | FORBIDDEN | 永久失败 | token 与 meta.tester_id 不匹配 |
| 413 | PAYLOAD_TOO_LARGE | 永久失败 | 单条录音超过 max_body_size |
| 415 | UNSUPPORTED_MEDIA_TYPE | 永久失败 | Content-Type 不是 multipart/form-data |
| 5xx | * | 重试 | 服务端临时错误，客户端按指数退避重试 |
| 507 | STORAGE_FULL | 重试 | 服务端磁盘空间不足，建议告警但继续 502 |

注：客户端把所有 5xx 与网络异常都视为「临时失败」放到 retry 队列。

### 1.7 存储布局

服务端推荐按如下结构落盘，与客户端 RecordingStore 镜像一致：

```
<storage_root>/
  <tester_id>/
    <sentence_id>/
      <recording_id>/
        audio.wav
        meta.json
        hypothesis.txt        # 可选
        _received_at          # 服务端写入的接收时间戳（ISO8601）
```

这是为了让后台 asr/tools/eval_wer.py 把客户端 export zip 与服务端落盘目录用同一份代码消费。任何不偏离此结构的方案都接受，但 eval_wer.py 默认按这个结构遍历。

### 1.8 不变量

合规服务必须满足：

1. 录音不丢：成功响应必须意味着 audio.wav 与 meta.json 已经 fsync 到持久化存储
2. 不重复存储：同 recording_id 二次上传不创建新目录
3. 不污染原 meta：服务端不修改 meta.json 任何字段；如需追加接收时间，写到独立的 _received_at 文件，不要塞回 meta
4. 不强制按时间排序：客户端只保证 recording_id 唯一、meta.recorded_at 单调，但上传到达顺序与 recorded_at 顺序无关

### 1.9 size 与速率限制

- 单条 audio.wav 上限建议 25 MB（约 13 分钟的 16kHz 16-bit mono），超过返回 413
- 服务端建议限速每 tester 每秒 1 请求，超出返回 429（客户端会当 5xx 重试）
- 单进程并发处理建议 ≤ 8（音频写盘是 IO 瓶颈，不是 CPU）

---

## 二、INFORMATIVE：FastAPI 参考实现

以下是最小可运行的参考实现，供云端实施者抄走即用。生产环境需补：

- TLS（建议 Nginx 终结，FastAPI 走 HTTP）
- 真实 token 校验（替换示例的 in-memory dict）
- 监控（Prometheus / 日志聚合）
- 备份策略

### 2.1 依赖

```text
fastapi==0.115.0
uvicorn[standard]==0.32.0
python-multipart==0.0.12
```

### 2.2 main.py

```python
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", "/var/lib/amphion-eval"))
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", 25 * 1024 * 1024))
SUPPORTED_SCHEMA_VERSIONS = {1}

# 生产环境从配置中心 / 环境变量 / Vault 拉取
TOKEN_TO_TESTER: Dict[str, str] = {
    os.environ["TOKEN_ALICE"]: "alice",
    os.environ["TOKEN_BOB"]: "bob",
}

app = FastAPI(title="Amphion Eval Collector", version="1.0.0")


def err(http: int, code: str, message: str):
    return JSONResponse(status_code=http, content={"code": code, "message": message})


def authenticate(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, {"code": "UNAUTHORIZED", "message": "missing bearer token"})
    token = authorization[len("Bearer "):]
    tester = TOKEN_TO_TESTER.get(token)
    if tester is None:
        raise HTTPException(401, {"code": "UNAUTHORIZED", "message": "invalid token"})
    return tester


@app.get("/v1/health")
def health():
    return {"status": "ok", "now": datetime.now(timezone.utc).isoformat()}


@app.post("/v1/recordings/{recording_id}")
async def upload(
    recording_id: str,
    request: Request,
    meta: UploadFile = File(...),
    audio: UploadFile = File(...),
    hypothesis: UploadFile | None = File(None),
    authorization: str | None = Header(None),
    x_amphion_schema_version: str | None = Header(None),
):
    tester = authenticate(authorization)

    # 校验 schema_version 头
    try:
        sv = int(x_amphion_schema_version or "0")
    except ValueError:
        return err(400, "SCHEMA_MISMATCH", "X-Amphion-Schema-Version not int")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        return err(400, "SCHEMA_MISMATCH", f"schema_version {sv} not supported")

    # 校验 audio 头
    if audio.content_type and "wav" not in audio.content_type and "octet-stream" not in audio.content_type:
        return err(415, "UNSUPPORTED_MEDIA_TYPE", f"audio content-type {audio.content_type}")

    # 读 meta，校验 recording_id 与 tester 一致性
    meta_bytes = await meta.read()
    try:
        meta_json = json.loads(meta_bytes)
    except json.JSONDecodeError:
        return err(400, "SCHEMA_MISMATCH", "meta is not valid JSON")
    if meta_json.get("recording_id") != recording_id:
        return err(400, "RECORDING_ID_MISMATCH", "URL recording_id != meta.recording_id")
    if meta_json.get("tester_id") != tester:
        return err(403, "FORBIDDEN", "token tester != meta.tester_id")
    if meta_json.get("schema_version") != sv:
        return err(400, "SCHEMA_MISMATCH", "header schema_version != meta.schema_version")

    sentence_id = meta_json.get("sentence_id")
    if not sentence_id:
        return err(400, "SCHEMA_MISMATCH", "meta.sentence_id missing")

    target_dir = STORAGE_ROOT / tester / sentence_id / recording_id

    # 幂等：目录已存在 → 直接返回 duplicate（不读旧 stored_at，避免引入额外文件）
    if (target_dir / "meta.json").exists():
        stored_at = datetime.fromtimestamp(
            (target_dir / "meta.json").stat().st_mtime, tz=timezone.utc
        ).isoformat()
        return {"status": "duplicate", "recording_id": recording_id, "stored_at": stored_at}

    # 写入到 _tmp 目录再 rename，保证 atomic
    tmp_dir = target_dir.with_name(f"{recording_id}._tmp")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        (tmp_dir / "meta.json").write_bytes(meta_bytes)

        audio_bytes_written = 0
        audio_path = tmp_dir / "audio.wav"
        with audio_path.open("wb") as f:
            while chunk := await audio.read(1 << 20):
                f.write(chunk)
                audio_bytes_written += len(chunk)
                if audio_bytes_written > MAX_BODY_BYTES:
                    shutil.rmtree(tmp_dir)
                    return err(413, "PAYLOAD_TOO_LARGE", f"audio > {MAX_BODY_BYTES} bytes")

        if hypothesis is not None:
            (tmp_dir / "hypothesis.txt").write_bytes(await hypothesis.read())

        received_at = datetime.now(timezone.utc).isoformat()
        (tmp_dir / "_received_at").write_text(received_at)

        # 原子 rename
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        os.rename(tmp_dir, target_dir)
    except OSError as e:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if "No space left" in str(e):
            return err(507, "STORAGE_FULL", str(e))
        raise

    return {
        "status": "stored",
        "recording_id": recording_id,
        "received_at": received_at,
    }
```

### 2.3 启动

```bash
export STORAGE_ROOT=/var/lib/amphion-eval
export TOKEN_ALICE=$(openssl rand -hex 24)
export TOKEN_BOB=$(openssl rand -hex 24)
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2.4 Nginx 反代示例

```nginx
server {
    listen 443 ssl http2;
    server_name eval.example.com;

    client_max_body_size 30M;
    client_body_timeout 120s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

---

## 三、CONFORMANCE：curl 验收

凭以下命令跑通即视为合规。所有命令针对 base url 假设为 https://eval.example.com，token 为 hex24 字符串。

### 3.1 健康检查

```bash
curl -sf https://eval.example.com/v1/health
# 期望 200 {"status":"ok","now":"..."}
```

### 3.2 上传一条录音（首次）

```bash
TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx
RECORDING_ID=$(uuidgen | tr A-Z a-z)
cat > /tmp/meta.json <<EOF
{
  "schema_version": 1,
  "finalized": true,
  "recording_id": "$RECORDING_ID",
  "attempt_index": 1,
  "sentence_id": "zh_en_mixed_005",
  "category_id": "zh_en_mixed",
  "reference_text": "我们的 deadline 是下周五五月二十二号。",
  "tester_id": "alice",
  "tester_nickname": "Alice",
  "device": {"model":"Pixel 7","manufacturer":"Google","android_sdk":34,"abi":"arm64-v8a"},
  "app_version": "0.1.0",
  "sdk_version": "0.1.0",
  "model_id": null,
  "model_version": null,
  "recorded_at": "2026-05-19T10:47:00Z",
  "duration_ms": 4321,
  "sample_rate": 16000,
  "gain_db": 10.0,
  "audio_source": "VOICE_RECOGNITION",
  "env": {"location":"办公室","noise_level":"low","noise_level_db_estimate":null,"notes":""},
  "on_device_hypothesis": null,
  "on_device_wer_estimate": null,
  "upload": {"state":"pending","uploaded_at":null,"attempts":0,"last_error":null,"last_attempt_at":null,"server_url":null}
}
EOF

# 准备一个 1 秒的静音 WAV
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "anullsrc=cl=mono:r=16000" \
  -ac 1 -ar 16000 -t 1 -c:a pcm_s16le /tmp/audio.wav

curl -sv \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Amphion-Schema-Version: 1" \
  -F "meta=@/tmp/meta.json;type=application/json" \
  -F "audio=@/tmp/audio.wav;type=audio/wav" \
  https://eval.example.com/v1/recordings/$RECORDING_ID
# 期望 200 {"status":"stored","recording_id":"...","received_at":"..."}
```

### 3.3 幂等验收

```bash
# 重复同一 recording_id
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Amphion-Schema-Version: 1" \
  -F "meta=@/tmp/meta.json;type=application/json" \
  -F "audio=@/tmp/audio.wav;type=audio/wav" \
  https://eval.example.com/v1/recordings/$RECORDING_ID
# 期望 200 {"status":"duplicate",...}
```

### 3.4 token 失败

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer invalid_token" \
  -H "X-Amphion-Schema-Version: 1" \
  -F "meta=@/tmp/meta.json;type=application/json" \
  -F "audio=@/tmp/audio.wav;type=audio/wav" \
  https://eval.example.com/v1/recordings/$(uuidgen | tr A-Z a-z)
# 期望 401
```

### 3.5 跨 tester

把 meta.tester_id 改成 "bob"，仍用 alice 的 token：

```bash
sed -i.bak 's/"tester_id": "alice"/"tester_id": "bob"/' /tmp/meta.json
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Amphion-Schema-Version: 1" \
  -F "meta=@/tmp/meta.json;type=application/json" \
  -F "audio=@/tmp/audio.wav;type=audio/wav" \
  https://eval.example.com/v1/recordings/$(uuidgen | tr A-Z a-z)
# 期望 403
```

### 3.6 schema 不支持

```bash
sed -i.bak 's/"schema_version": 1/"schema_version": 99/' /tmp/meta.json
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Amphion-Schema-Version: 99" \
  -F "meta=@/tmp/meta.json;type=application/json" \
  -F "audio=@/tmp/audio.wav;type=audio/wav" \
  https://eval.example.com/v1/recordings/$(uuidgen | tr A-Z a-z)
# 期望 400 SCHEMA_MISMATCH
```

---

## 四、版本与变更

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| 1.0.0 | 2026-05-19 | 初始版本：单条上传 + 幂等 + Bearer token + multipart |

变更规则：

- schema_version 与本文档版本号独立：协议变更（如新增字段、改变错误码语义）必须 bump 本文档版本，并同步 docs/eval/SCHEMA.md
- 不向后兼容的变更必须客户端先升级，服务端要支持新旧两版本一段时间（建议 ≥ 90 天）

---

## 五、与本仓库的关联

| 仓库内位置 | 角色 |
| --- | --- |
| asr/android/sample/src/main/java/com/amphion/asr/sample/eval/upload/HttpUploader.kt | 客户端实现 |
| docs/eval/SCHEMA.md | meta.json 完整字段定义 |
| docs/eval/WORKFLOW.md | 测试员手册 + 工程师手册 |
| asr/tools/eval_wer.py | 拿到服务端落盘数据后跑 WER 报告（与 zip 导出共用同一份代码） |
| shared/api-spec/errcodes.yaml | 4010~4015 上传错误码定义 |
