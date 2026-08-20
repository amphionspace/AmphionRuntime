#!/usr/bin/env python3
"""Generate the checked-in, deterministic 200-case hotword evaluation fixture."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import random
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "fixtures" / "hotword_eval_200.jsonl"
SEED = 20260820
PER_STRATUM = 25

# The order is part of the fixture contract.  Each stratum contributes exactly 25 cases.
STRATA = (
    ("zh_cv_clean", "zh-CN", "commonvoice_zh_hotwords",
     "common_voice_zh/lhotse/hotwords/cv-zh-CN_recordings_test.jsonl.gz",
     "common_voice_zh/lhotse/hotwords/cv-zh-CN_supervisions_test_punc_hotwords.jsonl.gz"),
    ("zh_aishell3_clean", "zh-CN", "aishell3_hotwords",
     "data_aishell3/lhotse/hotwords/aishell3_recordings_test.jsonl.gz",
     "data_aishell3/lhotse/hotwords/aishell3_supervisions_test_punc_hotwords.jsonl.gz"),
    ("zh_cv_noise", "zh-CN", "cv_zh_noise_musan_noise_hotwords",
     "degradation/cv_zh_test/noise_musan_noise/manifests/cv_zh_test_noise_musan_noise_recordings_degraded.jsonl.gz",
     "degradation/cv_zh_test/noise_musan_noise/manifests/cv_zh_test_noise_musan_noise_supervisions_hotwords.jsonl.gz"),
    ("zh_cv_rir", "zh-CN", "cv_zh_rir_slr26_hotwords",
     "degradation/cv_zh_test/rir_slr26/manifests/cv_zh_test_rir_slr26_recordings_degraded.jsonl.gz",
     "degradation/cv_zh_test/rir_slr26/manifests/cv_zh_test_rir_slr26_supervisions_hotwords.jsonl.gz"),
    ("en_cv_clean", "en-US", "commonvoice_en_hotwords",
     "common_voice_en/lhotse/hotwords/cv-en_recordings_test.jsonl.gz",
     "common_voice_en/lhotse/hotwords/cv-en_supervisions_test_orig_punc_hotwords.jsonl.gz"),
    ("en_libri_other", "en-US", "librispeech_test_other_hotwords",
     "LHOTSE/LibriSpeech/data/manifests/librispeech_recordings_test-other.jsonl.gz",
     "LHOTSE/LibriSpeech/data/manifests/librispeech_supervisions_test-other_hotwords.jsonl.gz"),
    ("en_cv_noise", "en-US", "cv_en_noise_musan_noise_hotwords",
     "degradation/cv_en_test/noise_musan_noise/manifests/cv_en_test_noise_musan_noise_recordings_degraded.jsonl.gz",
     "degradation/cv_en_test/noise_musan_noise/manifests/cv_en_test_noise_musan_noise_supervisions_hotwords.jsonl.gz"),
    ("en_cv_rir", "en-US", "cv_en_rir_slr26_hotwords",
     "degradation/cv_en_test/rir_slr26/manifests/cv_en_test_rir_slr26_recordings_degraded.jsonl.gz",
     "degradation/cv_en_test/rir_slr26/manifests/cv_en_test_rir_slr26_supervisions_hotwords.jsonl.gz"),
)


def rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def relative_audio(source: str) -> str:
    prefix = "/ai_sds_wuzz/DATA_ASR/"
    if not source.startswith(prefix):
        raise ValueError(f"unexpected recording source root: {source}")
    return source[len(prefix):]


def literal_hotwords(text: str, words: list[str]) -> bool:
    folded = text.casefold()
    return bool(words) and all(word.strip() and word.casefold() in folded for word in words)


def generate(data_root: Path) -> list[dict[str, object]]:
    data_asr = data_root / "DATA_ASR"
    selected: list[dict[str, object]] = []
    # CommonVoice clean/noise/RIR strata must not silently select the same base utterance.
    used_recordings_by_language: dict[str, set[str]] = {"zh-CN": set(), "en-US": set()}

    for stratum_index, (stratum, language, dataset_id, recordings_rel, supervisions_rel) in enumerate(STRATA):
        recordings_path = data_asr / recordings_rel
        supervisions_path = data_asr / supervisions_rel
        recording_by_id = {str(item["id"]): item for item in rows(recordings_path)}
        candidates: list[dict[str, object]] = []
        for supervision in rows(supervisions_path):
            recording_id = str(supervision["recording_id"])
            recording = recording_by_id.get(recording_id)
            if recording is None:
                continue
            duration = float(supervision.get("duration", 0))
            start = float(supervision.get("start", 0))
            text = str(supervision.get("text", "")).strip()
            custom = supervision.get("custom")
            if not isinstance(custom, dict):
                continue
            hotwords = custom.get("hotwords")
            if not isinstance(hotwords, list):
                continue
            words = [str(word).strip() for word in hotwords if str(word).strip()]
            if not (2.0 <= duration <= 12.0 and start == 0.0 and 1 <= len(words) <= 3):
                continue
            if not text or not literal_hotwords(text, words):
                continue
            sources = recording.get("sources")
            if not isinstance(sources, list) or len(sources) != 1 or not isinstance(sources[0], dict):
                continue
            source = sources[0].get("source")
            if not isinstance(source, str):
                continue
            audio_rel = relative_audio(source)
            if not (data_asr / audio_rel).is_file():
                continue
            candidates.append({
                "stratum": stratum,
                "dataset_id": dataset_id,
                "language": language,
                "recording_id": recording_id,
                "reference": text,
                "hotwords": words,
                "duration": duration,
                "audio": audio_rel,
                "recordings_manifest": recordings_rel,
                "supervisions_manifest": supervisions_rel,
            })

        rng = random.Random(SEED + stratum_index)
        rng.shuffle(candidates)
        picked: list[dict[str, object]] = []
        is_commonvoice = "cv_" in stratum
        for item in candidates:
            recording_id = str(item["recording_id"])
            if is_commonvoice and recording_id in used_recordings_by_language[language]:
                continue
            picked.append(item)
            if is_commonvoice:
                used_recordings_by_language[language].add(recording_id)
            if len(picked) == PER_STRATUM:
                break
        if len(picked) != PER_STRATUM:
            raise RuntimeError(f"{stratum}: expected {PER_STRATUM} candidates, found {len(picked)}")
        selected.extend(picked)

    for index, item in enumerate(selected):
        item["fixture_index"] = index
        item["id"] = f"hw-{index:03d}"
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True,
                        help="Extracted bundle root containing DATA_ASR.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    entries = generate(args.data_root.expanduser().resolve())
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in entries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="ascii"
    )
    print(f"wrote {len(entries)} fixed cases to {args.output}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
