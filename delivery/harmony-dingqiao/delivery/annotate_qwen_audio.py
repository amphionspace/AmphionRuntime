#!/usr/bin/env python3
"""Optional research annotation only; never imported by the offline SDK.

Audio-only Qwen request, no expected speakers/text/SDK predictions. Save raw
response and word labels independently from any human reference. Each output
directory is new; errors are retained and never retried or overwritten.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import urllib.error
import urllib.request
import wave

MODEL = "qwen-audio-3.1-asr-flash"
ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def normalize(response: dict, duration_ms: float) -> dict:
    sentences = response.get("output", {}).get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("diarization response has no sentences")
    segments, issues = [], []
    for sentence_index, sentence in enumerate(sentences):
        # Word IDs preserve a switch inside one sentence. Do not copy a sentence
        # ID over missing word IDs, or merge uncertainty into a named speaker.
        words = sentence.get("words")
        units = words if isinstance(words, list) and words else [sentence]
        for unit_index, unit in enumerate(units):
            begin, end = unit.get("begin_time"), unit.get("end_time")
            if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    for v in (begin, end)) or not 0 <= begin <= end <= duration_ms):
                issues.append({"sentence": sentence_index, "unit": unit_index, "reason": "invalid timestamp"})
                continue
            speaker = unit.get("speaker_id")
            if isinstance(speaker, bool) or (speaker is not None and not isinstance(speaker, int)):
                issues.append({"sentence": sentence_index, "unit": unit_index, "reason": "invalid speaker id"})
                speaker = None
            segments.append({"beginTime": begin, "endTime": end, "speakerIndex": speaker,
                             "text": unit.get("text", "") + unit.get("punctuation", ""),
                             "sentenceIndex": sentence_index, "unitIndex": unit_index,
                             "source": "word" if units is words else "sentence"})
    return {"annotationStatus": "auxiliary-not-human-truth", "segments": segments,
            "issues": issues, "overlapStatus": "not established by sentence/word labels",
            "coverageStatus": "unadjudicated; unlabeled time is not proof of silence",
            "status": "INCONCLUSIVE" if issues or not segments else "ANNOTATED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY")
    args = parser.parse_args()
    key = os.environ.get(args.api_key_env)
    if not key:
        raise SystemExit(f"missing environment variable: {args.api_key_env}")
    data = args.audio.read_bytes()
    with wave.open(str(args.audio), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getcomptype() != "NONE":
            raise SystemExit("expected mono PCM16 WAV")
        duration_ms = wav.getnframes() * 1000 / wav.getframerate()
        sample_rate = wav.getframerate()
    encoded = base64.b64encode(data).decode("ascii")
    if duration_ms > 300000 or len(encoded) > 10 * 1024 * 1024:
        raise SystemExit("this annotation helper accepts <= 5 min and <= 10 MiB base64; do not truncate silently")
    parameters = {"format": "wav", "sample_rate": str(sample_rate), "speaker_diarization_enabled": True}
    payload = {"model": MODEL, "input": {"messages": [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": "data:audio/wav;base64," + encoded}}]}]},
        "parameters": parameters}
    args.output_dir.mkdir(parents=True, exist_ok=False)
    metadata = {"schemaVersion": 1, "requestedModel": MODEL, "endpoint": ENDPOINT,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "audioSha256": hashlib.sha256(data).hexdigest(), "durationMs": duration_ms,
                "sourceOffsetSeconds": 0, "truncated": False, "parameters": parameters,
                "annotationStatus": "auxiliary-not-human-truth", "prompt": "audio only",
                "expectedSpeakerCountSupplied": False, "sdkOutputSupplied": False,
                "modelRevision": "service alias; server did not pin weights"}
    def save(name, value):
        with (args.output_dir / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    save("request-metadata.json", metadata)
    request = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "X-DashScope-SSE": "disable"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        save("error.json", {"httpStatus": error.code, "body": error.read().decode(errors="replace").replace(key, "<redacted>")})
        print(json.dumps({"status": "FAILED", "httpStatus": error.code, "output": str(args.output_dir)}))
        return 1
    except (urllib.error.URLError, TimeoutError):
        save("error.json", {"status": "transport failure; no retry"})
        print(json.dumps({"status": "FAILED", "output": str(args.output_dir)}))
        return 1
    # Keep the exact service body for auditing; authorization is never logged.
    (args.output_dir / "response.json").write_bytes(raw.replace(key.encode(), b"<redacted>"))
    response = json.loads(raw)
    try:
        normalized = normalize(response, duration_ms)
    except ValueError as error:
        save("error.json", {"reason": str(error)})
        return 1
    normalized["audioSha256"] = metadata["audioSha256"]
    normalized["responseSha256"] = hashlib.sha256((args.output_dir / "response.json").read_bytes()).hexdigest()
    normalized["requestId"] = response.get("request_id")
    save("annotation.json", normalized)
    print(json.dumps({"status": normalized["status"], "segments": len(normalized["segments"]),
                      "speakerCount": len({s["speakerIndex"] for s in normalized["segments"] if s["speakerIndex"] is not None}),
                      "output": str(args.output_dir)}))
    return 0 if normalized["status"] == "ANNOTATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
