from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any


ERR_INVALID_ARGUMENT = 1001
ERR_AUDIO_FORMAT_MISMATCH = 1002
ERR_TOO_MANY_SESSIONS = 1004
ERR_DECODE_FAILED = 3003


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int
    encoding: str
    channels: int


@dataclass(frozen=True)
class StartRequest:
    trace_id: str
    client_app: str
    client_user_hash: str
    audio_format: AudioFormat
    hotwords: str
    include_token_timestamps: bool
    enable_endpoint: bool


def parse_json_frame(message: str) -> dict[str, Any]:
    try:
        data = json.loads(message)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON frame: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON frame must be an object")
    return data


def parse_start(data: dict[str, Any]) -> StartRequest:
    fmt = data.get("audio_format") or {}
    if not isinstance(fmt, dict):
        raise ValueError("audio_format must be an object")
    return StartRequest(
        trace_id=str(data.get("trace_id", "")),
        client_app=str(data.get("client_app", "")),
        client_user_hash=str(data.get("client_user_hash", "")),
        audio_format=AudioFormat(
            sample_rate=int(fmt.get("sample_rate", 0)),
            encoding=str(fmt.get("encoding", "pcm_s16le")).lower(),
            channels=int(fmt.get("channels", 0)),
        ),
        hotwords=str(data.get("hotwords", "")),
        include_token_timestamps=bool(data.get("include_token_timestamps", False)),
        enable_endpoint=bool(data.get("enable_endpoint", True)),
    )


def event(event_type: str, **payload: Any) -> str:
    body = {"type": event_type, "server_send_ns": time.monotonic_ns()}
    body.update(payload)
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def error_event(code: int, message: str) -> str:
    return event("error", code=code, message=message)


def partial_event(result: dict[str, Any], include_token_timestamps: bool) -> str:
    payload: dict[str, Any] = {"text": result.get("text", "")}
    if include_token_timestamps:
        payload["tokens"] = result.get("tokens", [])
        payload["timestamps"] = result.get("timestamps", [])
    return event("partial", **payload)


def final_event(result: dict[str, Any], include_token_timestamps: bool) -> str:
    payload: dict[str, Any] = {"text": result.get("text", ""), "confidence": 1.0}
    if include_token_timestamps:
        payload["tokens"] = result.get("tokens", [])
        payload["timestamps"] = result.get("timestamps", [])
    return event("final", **payload)
