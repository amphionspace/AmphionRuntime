#!/usr/bin/env python3
"""Build a target-speaker fixture for the Harmony/Android `speaker-vad-turn` device mode.

The mode asserts that the owner's words reach a public final and the next speaker's words do not.
Every release since 0.3.20 waived it because no target-speaker fixture existed in the repo or the
fetched bundles. This builds one from aishell3: three utterances of one speaker enrol the
voiceprint, and each case is that speaker followed immediately by a different speaker with no
silence between them, which is the reported "owner stops, someone else continues" scenario.

Required and forbidden texts come from decoding each half on its own with the host recognizer, not
from the corpus transcript, so a case asserts speaker attribution rather than ASR accuracy.
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import load_audio_mono16k  # noqa: E402

SAMPLE_RATE = 16000
MODEL = REPO_ROOT / "asr/harmony/sdk/src/main/resources/rawfile/amphion-models/zh-en/v1"
CLI = REPO_ROOT / "third_party/.derived/sherpa-onnx/build-host-macos/bin/sherpa-onnx"


def write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm.tobytes())


def decode(path: Path) -> str:
    result = subprocess.run(
        [str(CLI), f"--tokens={MODEL}/tokens.txt", f"--encoder={MODEL}/encoder.int8.ort",
         f"--decoder={MODEL}/decoder.ort", f"--joiner={MODEL}/joiner.int8.ort",
         "--model-type=zipformer2", "--num-threads=2", "--decoding-method=greedy_search",
         "--enable-endpoint=false", str(path)],
        capture_output=True, text=True)
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("{") and '"text"' in line:
            return json.loads(line)["text"]
    return ""


# The device applies punctuation and inverse text normalization after ASR, so an assertion must
# survive both. A long chunk gets split by an inserted comma ("黎耀祥笑称这" became "黎耀祥笑称，
# 这"), and anything countable is rewritten ("十六" became "16"), so assertions stay short and
# avoid number words entirely.
NUMBER_CHARS = set("零一二三四五六七八九十百千万亿幺两0123456789")


def distinctive(text: str, avoid: str, length: int) -> str | None:
    """Shortest punctuation-safe substring of `text`, free of digits, absent from `avoid`."""
    units = [c for c in text if c.isalnum()]
    for width in range(2, min(length, len(units)) + 1):
        for start in range(len(units) - width + 1):
            chunk = "".join(units[start:start + width])
            if not chunk or chunk in avoid:
                continue
            if any(c in NUMBER_CHARS for c in chunk):
                continue
            return chunk
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path,
                        default=Path.home() / ".cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--target-speaker", default="SSB1340")
    parser.add_argument("--enrollment", type=int, default=3)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument("--assert-chars", type=int, default=3)
    args = parser.parse_args()

    audio_dir = args.out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    recs = {}
    for line in gzip.open(args.dataset_dir / "aishell3_test_hotwords_500_recordings_packaged.jsonl.gz", "rt"):
        rec = json.loads(line)
        recs[rec["id"]] = rec["sources"][0]["source"]
    by_speaker: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for line in gzip.open(args.dataset_dir / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz", "rt"):
        sup = json.loads(line)
        by_speaker[sup["speaker"]].append((sup["recording_id"], float(sup["duration"]), sup["text"]))

    target = sorted(by_speaker[args.target_speaker], key=lambda item: -item[1])
    if len(target) < args.enrollment + args.cases:
        raise SystemExit(f"target speaker {args.target_speaker} has too few utterances")
    # Longest utterances enrol the voiceprint; the next ones are the owner half of each case.
    enrollment, owners = target[:args.enrollment], target[args.enrollment:args.enrollment + args.cases]
    # Others are the shortest utterances of other speakers: a short interjection is the case the
    # streaming departure rule is weakest on, because the owner's tail dilutes the scoring window.
    # Short interjections are the case the streaming departure rule is weakest on, because the
    # owner's tail dilutes the scoring window. Skip transcripts that are mostly number words,
    # whose device text is rewritten by ITN and cannot be asserted literally.
    def assertable(text: str) -> bool:
        units = [c for c in text if c.isalnum()]
        return len(units) >= 4 and sum(1 for c in units if c in NUMBER_CHARS) * 2 < len(units)

    others = sorted(
        ((rid, dur, text, spk) for spk, items in by_speaker.items() if spk != args.target_speaker
         for rid, dur, text in items if assertable(text)),
        key=lambda item: item[1])[:args.cases]

    files: list[dict[str, object]] = []
    for index, (rid, dur, _text) in enumerate(enrollment):
        samples, _ = load_audio_mono16k(args.dataset_dir / recs[rid])
        name = f"enroll-{index:02d}-{rid}.wav"
        write_wav(audio_dir / name, samples)
        files.append({"role": "enrollment", "path": f"audio/{name}", "duration_sec": round(dur, 2)})
        print(f"[enroll] {name} {dur:.1f}s", file=sys.stderr)

    for index, ((o_rid, o_dur, _ot), (x_rid, x_dur, _xt, x_spk)) in enumerate(zip(owners, others)):
        owner, _ = load_audio_mono16k(args.dataset_dir / recs[o_rid])
        other, _ = load_audio_mono16k(args.dataset_dir / recs[x_rid])
        owner_wav = audio_dir / f"part-owner-{index:02d}.wav"
        other_wav = audio_dir / f"part-other-{index:02d}.wav"
        write_wav(owner_wav, owner)
        write_wav(other_wav, other)
        owner_text, other_text = decode(owner_wav), decode(other_wav)
        required = distinctive(owner_text, other_text, args.assert_chars)
        forbidden = distinctive(other_text, owner_text, args.assert_chars)
        owner_wav.unlink()
        other_wav.unlink()
        if required is None or forbidden is None:
            print(f"[skip] case {index}: no distinctive text ({owner_text!r} / {other_text!r})", file=sys.stderr)
            continue
        name = f"case-{index:02d}-{o_rid}-then-{x_spk}.wav"
        write_wav(audio_dir / name, np.concatenate([owner, other]))
        files.append({
            "role": "case", "path": f"audio/{name}", "case_id": f"turn-{index:02d}",
            "required_texts": [required], "forbidden_texts": [forbidden],
            # The owner prefix is the only non-empty public final; the replayed non-target suffix is
            # published as an empty final with a SPEAKER_VAD_REJECTED event.
            "expected_nonempty_public_finals": 1,
            "allow_finish_recovery": True,
            "owner_recording": o_rid, "other_recording": x_rid, "other_speaker": x_spk,
            "owner_sec": round(o_dur, 2), "other_sec": round(x_dur, 2),
            "owner_decoded": owner_text, "other_decoded": other_text,
        })
        print(f"[case] {name} owner {o_dur:.1f}s + other {x_dur:.1f}s  "
              f"required={required!r} forbidden={forbidden!r}", file=sys.stderr)

    manifest = {
        "schema": "target-speaker-fixture/1",
        "source_corpus": "aishell3_test_hotwords_500",
        "target_speaker": args.target_speaker,
        "note": ("Owner followed immediately by a different speaker with no silence. Required and "
                 "forbidden texts come from decoding each half alone with the host recognizer."),
        "files": files,
    }
    (args.out_dir / "target_speaker_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cases = sum(1 for f in files if f["role"] == "case")
    print(f"[done] {args.enrollment} enrollment + {cases} cases -> {args.out_dir}", file=sys.stderr)
    return 0 if cases else 1


if __name__ == "__main__":
    raise SystemExit(main())
