#!/usr/bin/env python3
"""Replay the speaker-turn split resolver on speaker-disjoint target + other sessions.

Host check for the Android port of `SpeakerTurnFinalizer` (the Harmony clean-split design):
for every consecutive pair of aishell3 recordings with different speakers, concatenate
`target + other` with no silence, enrol the target from its own audio, replay the fixed Speaker
VAD schedule, and when the state machine confirms a departure run the acoustic resolver exactly
as the SDK does (quiet-valley / score-change / coarse-grid candidates, contrast ranking, two
verified candidates). It reports where the resolved cut lands relative to the true boundary.

The resolver is replicated here because the SDK scorer needs the on-device embedding model; the
constants and ordering mirror `SpeakerTurnFinalizer.kt` / `SpeakerTurnFinalizer.ts`. Token
timestamps are not available without ASR, so the token candidates are empty; the device has
them as additional strong hints.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SV_SPEC = importlib.util.spec_from_file_location(
    "speaker_vad_aidatatang_shared", SCRIPT_DIR / "06_eval_speaker_vad_aidatatang.py"
)
assert SV_SPEC is not None and SV_SPEC.loader is not None
speaker_vad = importlib.util.module_from_spec(SV_SPEC)
sys.modules[SV_SPEC.name] = speaker_vad
SV_SPEC.loader.exec_module(speaker_vad)

from ts_asr import build_speaker, load_audio_mono16k  # noqa: E402

SAMPLE_RATE = 16000
MINIMUM_SPEAKER_SCORE_MARGIN = 0.15
MINIMUM_NON_TARGET_THRESHOLD_MARGIN = 0.05
SCORE_EPSILON = 0.000001


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if x.size else 0.0


def zcr(x: np.ndarray) -> float:
    if x.size < 2:
        return 0.0
    s = np.signbit(x)
    return float(np.count_nonzero(s[1:] != s[:-1])) / (x.size - 1)


def transition_contrast(samples: np.ndarray, candidate: int, span: int) -> float:
    left = samples[max(0, candidate - span):candidate]
    right = samples[candidate:min(samples.size, candidate + span)]
    rms_contrast = abs(math.log((rms(left) + 1e-6) / (rms(right) + 1e-6)))
    return rms_contrast + abs(zcr(left) - zcr(right))


def find_quiet_run(samples: np.ndarray, start: int, end: int, frame: int) -> tuple[int, int] | None:
    frames = [rms(samples[o:o + frame]) for o in range(start, end - frame + 1, frame)]
    if not frames:
        return None
    reference = max(frames)
    if reference <= 0:
        return None
    quiet_threshold = min(0.01, reference * 0.15)
    minimum_quiet = max(1, math.ceil(SAMPLE_RATE * 0.08 / frame))
    run_start = -1
    best = None
    for index in range(len(frames) + 1):
        quiet = index < len(frames) and frames[index] <= quiet_threshold
        if quiet and run_start < 0:
            run_start = index
        if quiet:
            continue
        if run_start >= 0 and index - run_start >= minimum_quiet:
            cs = start + run_start * frame
            ce = min(end, start + index * frame)
            if best is None or ce - cs > best[1] - best[0]:
                best = (cs, ce)
        run_start = -1
    return best


@dataclass
class Resolution:
    state: str
    endpoint_sec: float | None
    cut_sec: float | None
    reason: str
    embeddings: int


def replay(
    extractor,
    target_emb: np.ndarray,
    session: np.ndarray,
    *,
    threshold: float,
    win: int,
    hop: int,
    consecutive_below: int,
    max_buffer: int,
    finish_slice: int = 0,
) -> Resolution:
    """Replay the streaming schedule and resolve the first confirmed departure."""
    embeddings = 0

    def score(x: np.ndarray) -> float | None:
        nonlocal embeddings
        embeddings += 1
        emb = speaker_vad.window_embedding(extractor, x)
        return None if emb is None else float(np.dot(emb, target_emb))

    target_seen = False
    below = 0
    last_target_end = -1
    first_below_end = -1
    for end in range(win, session.size + 1, hop):
        s = score(session[end - win:end])
        if s is None:
            continue
        if s >= threshold:
            target_seen = True
            below = 0
            last_target_end = end
            first_below_end = -1
            continue
        below += 1
        if not target_seen:
            if below >= consecutive_below:
                return Resolution("pre_target_endpoint", end / SAMPLE_RATE, None, "pre-target", embeddings)
            continue
        if below == 1:
            first_below_end = end
        if below < consecutive_below:
            continue
        # departure confirmed at `end`; the SDK buffer holds everything up to here.
        retained = min(end, max_buffer)
        if end > max_buffer:
            return Resolution("endpoint", end / SAMPLE_RATE, None, "buffer-capped", embeddings)
        all_samples = session[:retained]
        search_start = max(0, last_target_end - win)
        search_end = min(all_samples.size, first_below_end)
        if search_end <= search_start:
            return Resolution("endpoint", end / SAMPLE_RATE, None, "invalid-search-range", embeddings)
        frame = max(1, round(SAMPLE_RATE / 50))
        refine = win
        candidates: list[int] = []
        lacked_context = False

        def add(sample: float) -> None:
            nonlocal lacked_context
            c = int(round(sample))
            if c < search_start or c > search_end or c <= 0 or c >= all_samples.size or c in candidates:
                return
            if c < refine or all_samples.size - c < refine:
                lacked_context = True
                return
            candidates.append(c)

        quiet = find_quiet_run(all_samples, search_start, search_end, frame)
        if quiet is not None:
            add(quiet[1])  # no token timestamps on host: align to the run end
        preferred_count = len(candidates)
        add(first_below_end - round(win / 2))
        coarse = max(frame, round(hop / 2))
        c = search_start
        while c <= search_end:
            add(c)
            c += coarse
        add(search_end)
        if not candidates:
            reason = "insufficient-refine-context" if lacked_context else "no-boundary-candidates"
            return Resolution("endpoint", end / SAMPLE_RATE, None, reason, embeddings)
        preferred = candidates[:preferred_count]
        acoustic = sorted(candidates[preferred_count:],
                          key=lambda p: -transition_contrast(all_samples, p, refine))
        ranked = preferred[:1] + acoustic
        best = -1
        best_margin = -math.inf
        for point in ranked[:2]:
            left = score(all_samples[point - refine:point])
            right = score(all_samples[point:point + refine])
            if left is None or right is None:
                continue
            if (left < threshold or right >= threshold or left - right < MINIMUM_SPEAKER_SCORE_MARGIN or
                    right > threshold - MINIMUM_NON_TARGET_THRESHOLD_MARGIN + SCORE_EPSILON):
                continue
            margin = left - right
            if margin > best_margin or (margin == best_margin and point > best):
                best = point
                best_margin = margin
        if best <= 0:
            return Resolution("endpoint", end / SAMPLE_RATE, None,
                              f"no-verified-boundary:candidates={len(candidates)}", embeddings)
        return Resolution("split", end / SAMPLE_RATE, best / SAMPLE_RATE, "split", embeddings)
    if target_seen and finish_slice > 0:
        # The streaming test scores the utterance's trailing window, which a
        # departing owner's own tail keeps above threshold when the next
        # speaker's turn is shorter than about one window plus one hop. At the
        # moment the utterance is finalized, score only the last `finish_slice`
        # instead: whoever spoke last dominates a short slice.
        tail = session[max(0, session.size - finish_slice):]
        s_tail = score(tail)
        if s_tail is not None and s_tail < threshold:
            cut = max(0, last_target_end - win) if last_target_end > 0 else 0
            return Resolution("finish_departure", session.size / SAMPLE_RATE,
                              (cut / SAMPLE_RATE) if cut > 0 else None,
                              f"finish-slice:{s_tail:.3f}", embeddings)
    state = "target_confirmed_no_endpoint" if target_seen else "target_not_confirmed"
    return Resolution(state, None, None, state, embeddings)


def describe(values: list[float]) -> dict:
    return speaker_vad.describe(values)


def evaluate(pairs: list[dict], *, label: str, threshold: float, win_sec: float, hop_sec: float,
             consecutive_below: int, extractor, truncation_tolerance_sec: float,
             finish_slice_sec: float = 0.0, controls: list[dict] | None = None) -> dict:
    win = int(win_sec * SAMPLE_RATE)
    hop = int(hop_sec * SAMPLE_RATE)
    finish_slice = int(finish_slice_sec * SAMPLE_RATE)
    states: dict[str, int] = {}
    reasons: dict[str, int] = {}
    cut_errors: list[float] = []
    leak_endpoint_only: list[float] = []
    leak_with_split: list[float] = []
    truncations_split = 0
    truncations_endpoint = 0
    embeddings = 0
    started = time.time()
    for rec in pairs:
        target_sec = rec["target_sec"]
        other_sec = rec["other_sec"]
        total_sec = target_sec + other_sec
        r = replay(extractor, rec["target_emb"], rec["session"], threshold=threshold, win=win, hop=hop,
                   consecutive_below=consecutive_below, max_buffer=25 * SAMPLE_RATE,
                   finish_slice=finish_slice)
        embeddings += r.embeddings
        states[r.state] = states.get(r.state, 0) + 1
        reasons[r.reason.split(":")[0]] = reasons.get(r.reason.split(":")[0], 0) + 1
        endpoint_sec = r.endpoint_sec if r.endpoint_sec is not None else total_sec
        leak_endpoint = min(max(endpoint_sec - target_sec, 0.0), other_sec)
        leak_endpoint_only.append(leak_endpoint)
        if endpoint_sec < target_sec - truncation_tolerance_sec:
            truncations_endpoint += 1
        if r.cut_sec is not None:
            cut_errors.append(r.cut_sec - target_sec)
            leak_with_split.append(min(max(r.cut_sec - target_sec, 0.0), other_sec))
            if r.cut_sec < target_sec - truncation_tolerance_sec:
                truncations_split += 1
        else:
            leak_with_split.append(leak_endpoint)
    n = len(pairs)
    control_fires = 0
    control_states: dict[str, int] = {}
    for rec in controls or []:
        c = replay(extractor, rec["target_emb"], rec["target_only"], threshold=threshold, win=win,
                   hop=hop, consecutive_below=consecutive_below, max_buffer=25 * SAMPLE_RATE,
                   finish_slice=finish_slice)
        control_states[c.state] = control_states.get(c.state, 0) + 1
        if c.state in ("split", "endpoint", "finish_departure", "pre_target_endpoint"):
            control_fires += 1
    return {
        "label": label,
        "finish_slice_sec": finish_slice_sec,
        "control_pairs": len(controls or []),
        "control_false_fire_rate": control_fires / max(1, len(controls or [])),
        "control_states": control_states,
        "threshold": threshold, "win_sec": win_sec, "hop_sec": hop_sec, "consecutive_below": consecutive_below,
        "n_pairs": n,
        "states": states,
        "resolution_reasons": reasons,
        "split_rate": states.get("split", 0) / n,
        "departure_rate": (states.get("split", 0) + states.get("endpoint", 0) +
                           states.get("finish_departure", 0)) / n,
        "cut_error_sec": describe(cut_errors),
        "avg_leak_endpoint_only_sec": sum(leak_endpoint_only) / n,
        "avg_leak_with_split_sec": sum(leak_with_split) / n,
        "leak_reduction_vs_endpoint_only": (
            1.0 - sum(leak_with_split) / sum(leak_endpoint_only) if sum(leak_endpoint_only) > 0 else None),
        "truncation_rate_endpoint_only": truncations_endpoint / n,
        "truncation_rate_with_split": truncations_split / n,
        "embeddings_per_pair": embeddings / n,
        "elapsed_sec": time.time() - started,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset-dir", type=Path, default=speaker_vad.TEST_DATA_ROOT / "aishell3_test_hotwords_500")
    p.add_argument("--speaker-model", type=Path, default=Path("shared/models/asr/dingqiao/eres2net.onnx"))
    p.add_argument("--out-dir", type=Path, default=Path("asr/tools/speaker/results/speaker_turn_split_aishell3"))
    p.add_argument("--max-pairs", type=int, default=None)
    p.add_argument("--num-threads", type=int, default=2)
    args = p.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    samples = speaker_vad.load_samples(args.dataset_dir)
    extractor = build_speaker(args.speaker_model.resolve(), num_threads=args.num_threads)
    audio = {}
    embs = {}
    for s in samples:
        x, _ = load_audio_mono16k(s.audio_path)
        audio[s.recording_id] = x
        embs[s.recording_id] = speaker_vad.embedding_for_samples(extractor, x)
    pairs = []
    for i, target in enumerate(samples):
        other = samples[(i + 1) % len(samples)]
        if other.speaker == target.speaker:
            continue  # same-speaker neighbours are not a turn
        ta, oa = audio[target.recording_id], audio[other.recording_id]
        pairs.append({
            "target_id": target.recording_id, "other_id": other.recording_id,
            "target_sec": ta.size / SAMPLE_RATE, "other_sec": oa.size / SAMPLE_RATE,
            "session": np.concatenate([ta, oa]), "target_emb": embs[target.recording_id],
            # Control: the same owner speaking alone. Any departure fired here would
            # truncate the owner's own sentence.
            "target_only": ta,
        })
        if args.max_pairs and len(pairs) >= args.max_pairs:
            break
    print(f"[INFO] {len(samples)} samples, {len(pairs)} speaker-disjoint pairs", file=sys.stderr)
    configs = [
        ("android-default 0.35/1.5/0.5/2", 0.35, 1.5, 0.5, 2, 0.0),
        ("+finish 0.8s", 0.35, 1.5, 0.5, 2, 0.8),
        ("+finish 1.2s", 0.35, 1.5, 0.5, 2, 1.2),
    ]
    rows = []
    for label, thr, win, hop, below, fin in configs:
        row = evaluate(pairs, label=label, threshold=thr, win_sec=win, hop_sec=hop, consecutive_below=below,
                       extractor=extractor, truncation_tolerance_sec=hop, finish_slice_sec=fin,
                       controls=pairs)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "elapsed_sec"}, ensure_ascii=False), file=sys.stderr)
    (args.out_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["| 配置 | 对数 | 未检出离场 | 触发离场 | 得到切点 | 平均泄露 (s) | 对照组误触发 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        missed = r["states"].get("target_confirmed_no_endpoint", 0) + r["states"].get("target_not_confirmed", 0)
        lines.append(f"| {r['label']} | {r['n_pairs']} | {missed} ({missed / r['n_pairs']:.1%}) | "
                     f"{r['departure_rate']:.1%} | {r['split_rate']:.1%} | "
                     f"{r['avg_leak_with_split_sec']:.2f} | {r['control_false_fire_rate']:.1%} |")
    (args.out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
