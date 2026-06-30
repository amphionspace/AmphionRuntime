# AmphionRuntime 流式语音识别服务 gRPC 接口文档

本文面向接入方,描述流式语音识别(ASR)服务端的 gRPC 接口、调用流程、字段语义、错误处理与最小示例。

## 1. 概述

服务通过 gRPC 提供实时流式语音识别。客户端以双向流方式持续上送音频,服务端实时返回中间结果(partial)与最终结果(final),并在检测到句子停顿时返回断点(endpoint)。

- 协议:gRPC over HTTP/2
- 序列化:Protocol Buffers(proto3)
- package:asr.v1
- 服务名:asr.v1.AsrService

## 2. 连接与传输

- 端点:host:port,例如 your-host:50051(以实际部署为准)
- 默认明文传输(h2c);如需加密,建议在接入层(反向代理/网关)启用 TLS
- 单条消息大小上限:8 MB

接入方需基于随附的 asr.proto 生成对应语言的 stub(支持 Python / Java / Go / C++ / Node 等所有 gRPC 官方语言)。接口完整定义见本文第 11 节。

## 3. 接口方法

服务 asr.v1.AsrService 提供三个方法:

| 方法 | 类型 | 说明 |
| --- | --- | --- |
| Recognize | 双向流 stream PcmRequest 返回 stream AsrEvent | 流式识别主接口 |
| Healthz | 一元 | 健康检查 |
| ServerInfo | 一元 | 查询服务端版本与当前模型信息 |

## 4. Recognize 调用流程

一次完整的识别会话按如下顺序进行:

1. 客户端建立 Recognize 双向流。
2. 客户端发送的第一帧必须是 SessionConfig(声学参数、热词、是否返回时间戳等)。若首帧不是 SessionConfig,服务端以 INVALID_ARGUMENT 关闭流。
3. 客户端持续发送 AudioChunk(PCM 音频分片),建议每帧 100 ms。
4. 服务端异步返回 AsrEvent 事件流:先回 SessionStarted,随后在识别过程中穿插返回 AsrPartial(中间结果)、AsrEndpoint(断点)、AsrFinal(最终结果)。
5. 客户端可在两句话之间发送 UpdateHotwordsRequest 更新热词(可选)。
6. 客户端发送 EndOfStream 表示音频结束,服务端 flush 出最后的 AsrFinal,并返回 SessionEnded,然后正常关闭流。

时序示意:

```
client  ──SessionConfig──────────────────────────────────▶ server
client  ──AudioChunk──AudioChunk──AudioChunk── ... ───────▶ server
server  ◀──SessionStarted──Partial──Partial──Endpoint──Final── ...
client  ──EndOfStream─────────────────────────────────────▶ server
server  ◀──Final──SessionEnded──(关闭)
```

## 5. 请求消息 PcmRequest

PcmRequest 是 oneof,每帧只能是以下之一:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| session_config | SessionConfig | 必须为第一帧,且仅一次 |
| audio_chunk | AudioChunk | 音频分片 |
| end_of_stream | EndOfStream | 输入结束标志 |
| update_hotwords | UpdateHotwordsRequest | 运行时更新热词(可选) |

### 5.1 SessionConfig

| 字段 | 类型 | 是否生效 | 说明 |
| --- | --- | --- | --- |
| trace_id | string | 生效(回显) | 业务追踪号,仅用于日志,会在 SessionEnded 中原样返回 |
| client_app | string | 仅日志 | 客户端标识,例如 android-1.1.0 |
| client_user_hash | string | 仅日志 | 不含个人身份的聚合统计标识 |
| audio_format | AudioFormat | 生效 | 音频格式,见 6 节;不匹配会被拒绝 |
| decoding | Decoding | 当前由服务端统一配置 | 见下方说明 |
| hotwords | HotwordSpec | 生效 | 本次会话初始热词 |
| enable_endpoint | bool | 当前由服务端统一配置 | 服务端默认开启断点检测 |
| include_token_timestamps | bool | 生效 | 为 true 时,partial/final 附带逐 token 文本与时间戳 |

重要说明(与 proto 字段定义的实际差异):

- decoding(解码方法、束宽、同音替换、ITN、语言模型开关)当前由服务端按部署统一配置,SessionConfig.decoding 不按单次请求生效。如需调整请联系服务提供方。
- enable_endpoint 当前固定由服务端开启,SessionConfig.enable_endpoint 不按单次请求生效。
- 因此接入方只需可靠设置 audio_format、hotwords、include_token_timestamps 三类字段。

### 5.2 AudioFormat

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| sample_rate | int32 | 必须与服务端模型一致(可由 ServerInfo 查询,常见为 16000) |
| encoding | AudioEncoding | PCM_S16LE 或 PCM_F32LE |
| channels | int32 | 必须为 1(单声道) |

AudioEncoding 枚举:

| 值 | 含义 |
| --- | --- |
| AUDIO_ENCODING_UNSPECIFIED | 未指定(非法) |
| PCM_S16LE | 16-bit 有符号小端 |
| PCM_F32LE | 32-bit 浮点小端 |

### 5.3 HotwordSpec

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| words_text | string | 热词串,每行一个词,可选 ":score";例如 "语音识别 :2.0\n端到端 :1.5" |
| score | float | 全局默认权重,词未自带 :score 时使用,默认 1.5 |

### 5.4 AudioChunk

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| data | bytes | 一段 PCM 原始字节,建议 100 ms 一帧(16k 单声道 PCM_S16LE 为 3200 字节) |
| client_send_us | int64 | 客户端发送时间戳(微秒),可选,便于统计端到端延迟 |

### 5.5 UpdateHotwordsRequest

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| hotwords | HotwordSpec | 新热词;在两句话之间发送,当前未完成的中间结果会被丢弃后重新开始 |

### 5.6 EndOfStream

空消息,通知服务端输入结束,请 flush 出最后的最终结果。

## 6. 响应事件 AsrEvent

AsrEvent 含一个公共字段与一个 oneof payload:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| server_send_ns | int64 | 服务端发送时间戳(纳秒),用于排查延迟 |
| payload | oneof | 见下表 |

payload 取值:

| 类型 | 触发时机 | 关键字段 |
| --- | --- | --- |
| session_started | 会话建立后立即返回一次 | 无 |
| partial | 识别过程中文本更新时 | text,可选 tokens/timestamps |
| endpoint | 检测到句子停顿(断点) | 无;其后的结果属于新一句 |
| final | 一句话识别完成,或收到 EndOfStream | text、confidence、可选 tokens/timestamps |
| error | 运行时错误 | code、message |
| session_ended | 会话正常结束 | trace_id |

### 6.1 AsrPartial / AsrFinal 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| text | string | 识别文本 |
| confidence | float | 仅 final 有;当前为占位值,固定返回 1.0,不代表真实置信度 |
| tokens | string 数组 | 仅当 include_token_timestamps 为 true 时填充 |
| timestamps | float 数组 | 逐 token 时间戳(秒),同上条件填充 |
| token_confidences | float 数组 | 当前不填充(预留) |

## 7. 错误处理

服务端的错误通过两种渠道返回,接入方都需处理:

### 7.1 gRPC 状态码(导致流终止)

| gRPC StatusCode | 触发原因 | 建议处理 |
| --- | --- | --- |
| INVALID_ARGUMENT | 首帧不是 SessionConfig;或在发送 SessionConfig 前关闭;或 audio_format 与模型不匹配(采样率不符、非单声道) | 修正参数后重建会话,不要重试原参数 |
| RESOURCE_EXHAUSTED | 服务端活跃会话已达上限 | 退避后重试,或扩容服务端 |
| INTERNAL | 服务端内部错误(会话创建失败、解码异常等) | 关闭并重建会话 |

### 7.2 AsrEvent.error(流内错误事件)

| code | 含义 | 建议处理 |
| --- | --- | --- |
| 3003 | 会话长时间无音频被服务端断开(空闲超时) | 关闭并按需重建会话 |

说明:服务端在 Recognize 链路实际返回的业务码集中在配置类与运行时类。完整错误码表为多端共享集合(含端侧 SDK 的下载、授权等场景),其中大部分不会由本服务端通过 Recognize 返回,接入方按上表处理即可。

## 8. 音频要求小结

- 采样率:与服务端模型一致(以 ServerInfo 为准,常见 16000 Hz)
- 声道:单声道(channels = 1)
- 位深/编码:PCM_S16LE 或 PCM_F32LE
- 分片粒度:建议每帧 100 ms;过大延迟升高,过小系统调用开销增加
- 首帧必须为 SessionConfig,其后才是音频

## 9. 健康检查与服务信息

### 9.1 Healthz

请求 HealthzRequest 为空;响应 HealthzResponse:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| status | enum | SERVING / NOT_SERVING / UNKNOWN |
| active_sessions | int64 | 当前活跃会话数 |
| recent_rtf | double | 近期实时率(预留) |

### 9.2 ServerInfo

请求 ServerInfoRequest 为空;响应 ServerInfoResponse:

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| sdk_version | string | 服务端版本 |
| sherpa_onnx_version | string | 推理引擎版本 |
| model_manifest_json | string | 当前模型的元信息 JSON,含 model_id、version、sample_rate、feature_dim、lang 等 |
| uptime_seconds | int64 | 服务运行时长(秒) |

接入前建议先调用 ServerInfo 读取 sample_rate,据此设置 AudioFormat。

## 10. 最小调用示例(Python)

先安装依赖并生成 stub:

```bash
pip install grpcio grpcio-tools protobuf
python -m grpc_tools.protoc -I . --python_out=. --grpc_python_out=. asr.proto
```

最小客户端:

```python
import grpc, wave
import asr_pb2 as pb
import asr_pb2_grpc as pb_grpc

def requests(wav_path):
    # 第一帧:SessionConfig
    cfg = pb.SessionConfig(
        trace_id="demo-1",
        audio_format=pb.AudioFormat(
            sample_rate=16000, encoding=pb.PCM_S16LE, channels=1),
        include_token_timestamps=False,
    )
    cfg.hotwords.words_text = "语音识别 :2.0"
    yield pb.PcmRequest(session_config=cfg)

    # 音频帧:每 100 ms 一片(16k 单声道 = 3200 字节)
    with wave.open(wav_path, "rb") as w:
        frame_bytes = int(16000 * 0.1) * 2
        while True:
            data = w.readframes(int(16000 * 0.1))
            if not data:
                break
            yield pb.PcmRequest(audio_chunk=pb.AudioChunk(data=data))

    # 结束
    yield pb.PcmRequest(end_of_stream=pb.EndOfStream())

def main():
    ch = grpc.insecure_channel("your-host:50051")
    stub = pb_grpc.AsrServiceStub(ch)
    for ev in stub.Recognize(requests("test.wav")):
        which = ev.WhichOneof("payload")
        if which == "partial":
            print("partial:", ev.partial.text)
        elif which == "final":
            print("final  :", ev.final.text)
        elif which == "endpoint":
            print("--- endpoint ---")
        elif which == "error":
            print("error  :", ev.error.code, ev.error.message)
        elif which == "session_ended":
            print("ended  :", ev.session_ended.trace_id)

if __name__ == "__main__":
    main()
```

## 11. 接口定义(proto 摘录)

以下为接口的关键定义,完整 asr.proto 随交付提供。

```proto
syntax = "proto3";
package asr.v1;

service AsrService {
  rpc Recognize(stream PcmRequest) returns (stream AsrEvent);
  rpc Healthz(HealthzRequest) returns (HealthzResponse);
  rpc ServerInfo(ServerInfoRequest) returns (ServerInfoResponse);
}

message PcmRequest {
  oneof payload {
    SessionConfig session_config = 1;
    AudioChunk audio_chunk = 2;
    EndOfStream end_of_stream = 3;
    UpdateHotwordsRequest update_hotwords = 4;
  }
}

message SessionConfig {
  string trace_id = 1;
  string client_app = 2;
  string client_user_hash = 3;
  AudioFormat audio_format = 10;
  Decoding decoding = 11;
  HotwordSpec hotwords = 12;
  bool enable_endpoint = 13;
  bool include_token_timestamps = 14;
}

message AudioFormat {
  int32 sample_rate = 1;
  AudioEncoding encoding = 2;
  int32 channels = 3;
}

enum AudioEncoding {
  AUDIO_ENCODING_UNSPECIFIED = 0;
  PCM_S16LE = 1;
  PCM_F32LE = 2;
}

message Decoding {
  DecodingMethod method = 1;
  int32 max_active_paths = 2;
  HomophoneReplacer hr = 10;
  ItnConfig itn = 11;
  LmConfig lm = 12;
}

enum DecodingMethod {
  DECODING_METHOD_UNSPECIFIED = 0;
  GREEDY_SEARCH = 1;
  MODIFIED_BEAM_SEARCH = 2;
}

message HotwordSpec {
  string words_text = 1;
  float score = 2;
}

message HomophoneReplacer { bool enable = 1; }
message ItnConfig { bool enable = 1; repeated string rule_set = 2; }
message LmConfig { bool enable = 1; float scale = 2; }

message AudioChunk {
  bytes data = 1;
  int64 client_send_us = 2;
}

message EndOfStream {}
message UpdateHotwordsRequest { HotwordSpec hotwords = 1; }

message AsrEvent {
  int64 server_send_ns = 1;
  oneof payload {
    AsrPartial partial = 10;
    AsrFinal final = 11;
    AsrEndpoint endpoint = 12;
    AsrError error = 13;
    SessionStarted session_started = 14;
    SessionEnded session_ended = 15;
  }
}

message AsrPartial {
  string text = 1;
  repeated string tokens = 2;
  repeated float timestamps = 3;
  repeated float token_confidences = 4;
}

message AsrFinal {
  string text = 1;
  float confidence = 2;
  repeated string tokens = 3;
  repeated float timestamps = 4;
  repeated float token_confidences = 5;
}

message AsrEndpoint {}
message AsrError { int32 code = 1; string message = 2; }
message SessionStarted {}
message SessionEnded { string trace_id = 1; }

message HealthzRequest {}
message HealthzResponse {
  enum Status { UNKNOWN = 0; SERVING = 1; NOT_SERVING = 2; }
  Status status = 1;
  int64 active_sessions = 2;
  double recent_rtf = 3;
}

message ServerInfoRequest {}
message ServerInfoResponse {
  string sdk_version = 1;
  string sherpa_onnx_version = 2;
  string model_manifest_json = 3;
  int64 uptime_seconds = 4;
}
```
