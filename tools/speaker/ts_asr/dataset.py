"""ts_hw_test cuts manifest 加载层。

不依赖 lhotse；cuts.jsonl.gz 本质就是每行一个 JSON 对象，自己读 + 路径
rebase 比走 lhotse 加载链更可控。

数据探查结论（参考 [docs/Target_speaker.md] 6.x 节附近）：

- 6555 条 cuts，positive 6227 / negative_silence 164 / negative_distractor 164
- recording / enrollment 路径形如 `/chenmingjie/mingdong/data/lhotse/...`，
  本地映射到 `/Users/boxp/data/...`，rebase 命中率 100%
- positive 必带 overlap_ratio (0.1~0.7+)，num_interferers (1/2/3)
- negative 的 overlap_ratio / num_interferers 为 None / -1，speaker 字段仍保留

dataset.py 提供：

1. EvalSample dataclass：把每条 cut 收敛成评估侧需要的字段
2. TsHwTestDataset：iter() 支持按 sample_type / source_dataset / overlap_ratio 区间过滤
3. iter_speaker_enrollments()：按 target speaker 聚合 enrollment_audio，给"多模板注册"用
4. stats()：复刻探查阶段的分布表，供 03_eval.py 入口处再核对一次

加载策略：lazy stream，读 cuts.jsonl.gz 一次性 parse 到内存（< 10MB 文本，6555
条 dict，host 内存吃得下），后续 iter 是从内存切片，不重复 IO。
"""

from __future__ import annotations

import collections
import gzip
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Sequence

import numpy as np

from .core import TARGET_SAMPLE_RATE, load_audio_mono16k


DEFAULT_AUDIO_ROOT_REMOTE = "/chenmingjie/mingdong/data/lhotse/"
DEFAULT_AUDIO_ROOT_LOCAL = "/Users/boxp/data/"


@dataclass
class EvalSample:
    """一条评估样本。所有路径已经 rebase 到本地。

    audio / enrollment_audio 是惰性加载的：dataclass 里只放路径，调用 load_audio()
    才真正读 wav。这样 stats() / 分桶时不会因为读音频拖慢节奏。
    """

    cut_id: str
    sample_type: str
    speaker_id: str
    text: str
    language: str
    duration: float
    enrollment_duration: float
    overlap_ratio: Optional[float]
    num_interferers: Optional[int]
    target_snr_db: Optional[float]
    source_dataset: str
    noise_source: Optional[str]
    audio_path: Path
    enrollment_audio_path: Path
    interferer_speakers: list[str] = field(default_factory=list)

    @property
    def is_positive(self) -> bool:
        return self.sample_type == "positive"

    @property
    def is_chinese(self) -> bool:
        return (self.language or "").lower().startswith("zh")

    def load_audio(self) -> tuple[np.ndarray, int]:
        return load_audio_mono16k(self.audio_path)

    def load_enrollment_audio(self) -> tuple[np.ndarray, int]:
        return load_audio_mono16k(self.enrollment_audio_path)


def _rebase(remote_path: str, audio_root_remote: str, audio_root_local: str) -> Path:
    if remote_path.startswith(audio_root_remote):
        local = audio_root_local + remote_path[len(audio_root_remote) :]
        return Path(local)
    return Path(remote_path)


class TsHwTestDataset:
    """ts_hw_test cuts manifest 内存加载器。

    构造时一次性把 cuts.jsonl.gz 读到内存（list[EvalSample]），后续 iter 都是
    内存遍历。调用方对 audio_root_remote / audio_root_local 不满意时可以
    覆盖默认值。
    """

    def __init__(
        self,
        cuts_path: Path | str,
        *,
        audio_root_remote: str = DEFAULT_AUDIO_ROOT_REMOTE,
        audio_root_local: str = DEFAULT_AUDIO_ROOT_LOCAL,
        validate_paths: bool = False,
    ):
        self.cuts_path = Path(cuts_path)
        self.audio_root_remote = audio_root_remote
        self.audio_root_local = audio_root_local
        self._samples: list[EvalSample] = []
        self._load(validate_paths=validate_paths)

    def _load(self, *, validate_paths: bool) -> None:
        if not self.cuts_path.is_file():
            raise FileNotFoundError(f"cuts manifest 不存在: {self.cuts_path}")
        opener = gzip.open if str(self.cuts_path).endswith(".gz") else open
        with opener(str(self.cuts_path), "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                cut = json.loads(line)
                sup = cut["supervisions"][0]
                custom = sup.get("custom", {}) or {}
                rec_remote = cut["recording"]["sources"][0]["source"]
                enroll_remote = custom.get("enrollment_audio", "")
                sample = EvalSample(
                    cut_id=cut["id"],
                    sample_type=custom.get("sample_type", "?"),
                    speaker_id=sup.get("speaker") or "",
                    text=sup.get("text", "") or "",
                    language=sup.get("language") or "",
                    duration=float(cut.get("duration") or 0.0),
                    enrollment_duration=float(custom.get("enrollment_duration") or 0.0),
                    overlap_ratio=custom.get("overlap_ratio"),
                    num_interferers=custom.get("num_interferers"),
                    target_snr_db=custom.get("target_snr_db"),
                    source_dataset=custom.get("source_dataset") or "?",
                    noise_source=custom.get("noise_source"),
                    audio_path=_rebase(rec_remote, self.audio_root_remote, self.audio_root_local),
                    enrollment_audio_path=_rebase(
                        enroll_remote, self.audio_root_remote, self.audio_root_local
                    ),
                    interferer_speakers=list(custom.get("interferer_speakers") or []),
                )
                self._samples.append(sample)

        if validate_paths:
            missing = [
                s for s in self._samples
                if not s.audio_path.is_file() or not s.enrollment_audio_path.is_file()
            ]
            if missing:
                raise FileNotFoundError(
                    f"{len(missing)} 条样本的音频路径不存在；首条: {missing[0].audio_path}"
                )

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, idx: int) -> EvalSample:
        return self._samples[idx]

    def all(self) -> list[EvalSample]:
        return list(self._samples)

    def iter(
        self,
        *,
        sample_type: Optional[str] = None,
        source_dataset: Optional[str] = None,
        language: Optional[str] = None,
        overlap_min: Optional[float] = None,
        overlap_max: Optional[float] = None,
        num_interferers: Optional[int] = None,
        max_n: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> Iterator[EvalSample]:
        """按字段过滤 + 可选随机抽样。

        过滤语义：
        - sample_type='positive' 只保留 positive；'negative' 同时匹配 silence + distractor
        - overlap_min / overlap_max 仅对 overlap_ratio 不为 None 的样本生效
          （None 视为不参与重叠分桶；调用方如果只想要"有 overlap_ratio 标注的"，
           显式传 overlap_min=0.0 即可）
        - max_n + seed 一起用：先过滤再随机抽 max_n 条

        说明：分层抽样（每个桶各 N 条）由调用方组合多次 iter() 完成，本函数
        不再代为做分层；保持单一职责。
        """
        out: list[EvalSample] = []
        for s in self._samples:
            if sample_type:
                if sample_type == "negative":
                    if s.sample_type not in ("negative_silence", "negative_distractor"):
                        continue
                elif s.sample_type != sample_type:
                    continue
            if source_dataset and s.source_dataset != source_dataset:
                continue
            if language and (s.language or "").lower() != language.lower():
                continue
            if overlap_min is not None:
                if s.overlap_ratio is None or s.overlap_ratio < overlap_min:
                    continue
            if overlap_max is not None:
                if s.overlap_ratio is None or s.overlap_ratio >= overlap_max:
                    continue
            if num_interferers is not None and s.num_interferers != num_interferers:
                continue
            out.append(s)

        if max_n is not None and len(out) > max_n:
            rng = np.random.default_rng(seed)
            idxs = rng.permutation(len(out))[:max_n]
            out = [out[int(i)] for i in idxs]

        for s in out:
            yield s

    def iter_speaker_enrollments(
        self, *, sample_type: str = "positive"
    ) -> Iterator[tuple[str, list[Path]]]:
        """按 speaker_id 聚合 enrollment 路径。

        默认只聚合 positive；negative 的 speaker 字段含义不一致（silence 是配对的
        target speaker，distractor 是 hash 字符串），不在多模板注册范围。
        """
        bucket: dict[str, list[Path]] = collections.defaultdict(list)
        seen: dict[str, set[str]] = collections.defaultdict(set)
        for s in self._samples:
            if s.sample_type != sample_type:
                continue
            if not s.speaker_id or not s.enrollment_audio_path:
                continue
            key = str(s.enrollment_audio_path)
            if key in seen[s.speaker_id]:
                continue
            seen[s.speaker_id].add(key)
            bucket[s.speaker_id].append(s.enrollment_audio_path)
        for speaker_id in sorted(bucket.keys()):
            yield speaker_id, bucket[speaker_id]

    def stats(self) -> dict:
        """复刻数据探查阶段的分布表。便于 03_eval.py 入口处自检数据未变。"""
        out: dict = {
            "total": len(self._samples),
            "sample_type": collections.Counter(),
            "source_dataset": collections.Counter(),
            "language": collections.Counter(),
            "num_interferers": collections.Counter(),
            "overlap_ratio_buckets": collections.Counter(),
            "duration": {"min": float("inf"), "max": 0.0, "median": 0.0,
                          "lt_1_5s": 0, "lt_2_5s": 0},
            "unique_speakers_positive": set(),
            "unique_enrollments": set(),
            "audio_root_remote": self.audio_root_remote,
            "audio_root_local": self.audio_root_local,
        }
        durations: list[float] = []
        for s in self._samples:
            out["sample_type"][s.sample_type] += 1
            out["source_dataset"][s.source_dataset] += 1
            out["language"][s.language] += 1
            out["num_interferers"][
                s.num_interferers if s.num_interferers is not None else -1
            ] += 1
            o = s.overlap_ratio
            if o is None:
                bucket_key = "None"
            elif o == 0:
                bucket_key = "0.0"
            elif o < 0.1:
                bucket_key = "0-0.1"
            elif o < 0.2:
                bucket_key = "0.1-0.2"
            elif o < 0.3:
                bucket_key = "0.2-0.3"
            elif o < 0.5:
                bucket_key = "0.3-0.5"
            else:
                bucket_key = ">=0.5"
            out["overlap_ratio_buckets"][bucket_key] += 1

            durations.append(s.duration)
            out["duration"]["min"] = min(out["duration"]["min"], s.duration)
            out["duration"]["max"] = max(out["duration"]["max"], s.duration)
            if s.duration < 1.5:
                out["duration"]["lt_1_5s"] += 1
            if s.duration < 2.5:
                out["duration"]["lt_2_5s"] += 1

            if s.is_positive and s.speaker_id:
                out["unique_speakers_positive"].add(s.speaker_id)
            out["unique_enrollments"].add(str(s.enrollment_audio_path))

        if durations:
            durations.sort()
            mid = len(durations) // 2
            out["duration"]["median"] = (
                durations[mid] if len(durations) % 2 == 1
                else 0.5 * (durations[mid - 1] + durations[mid])
            )

        out["sample_type"] = dict(out["sample_type"])
        out["source_dataset"] = dict(out["source_dataset"])
        out["language"] = dict(out["language"])
        out["num_interferers"] = dict(out["num_interferers"])
        out["overlap_ratio_buckets"] = dict(out["overlap_ratio_buckets"])
        out["unique_speakers_positive"] = len(out["unique_speakers_positive"])
        out["unique_enrollments"] = len(out["unique_enrollments"])
        return out
