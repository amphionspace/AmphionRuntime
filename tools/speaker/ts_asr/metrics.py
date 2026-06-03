"""TS-ASR 评测指标。

调研期只需要 FAR / FRR / EER 三个段级二分类指标，与 ROC 阈值扫描。
ASR CER/WER 调研期暂不在本文件覆盖（等数据到位 + 03_eval.py 写时再补）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np


@dataclass
class BinaryMetrics:
    """段级二分类指标。

    target_count: 真值为 target 的段数
    other_count: 真值为非 target 的段数
    far: false accept rate = 非 target 段被判为 target 的比例
    frr: false reject rate = target 段被判为非 target 的比例
    """

    threshold: float
    target_count: int
    other_count: int
    far: float
    frr: float

    @property
    def accuracy(self) -> float:
        total = self.target_count + self.other_count
        if total == 0:
            return 0.0
        tp = self.target_count * (1 - self.frr)
        tn = self.other_count * (1 - self.far)
        return float((tp + tn) / total)


def binary_metrics(
    scores: Sequence[float], labels: Sequence[int], threshold: float
) -> BinaryMetrics:
    """labels: 1 = target, 0 = other。score >= threshold 视为判 target。"""
    s = np.asarray(scores, dtype=np.float32)
    y = np.asarray(labels, dtype=np.int32)
    if s.shape != y.shape:
        raise ValueError(f"shape mismatch: scores {s.shape} vs labels {y.shape}")
    pred = (s >= threshold).astype(np.int32)

    target_mask = y == 1
    other_mask = y == 0
    target_count = int(target_mask.sum())
    other_count = int(other_mask.sum())

    far = (
        float(pred[other_mask].sum() / other_count) if other_count > 0 else 0.0
    )
    frr_count = int((1 - pred[target_mask]).sum()) if target_count > 0 else 0
    frr = float(frr_count / target_count) if target_count > 0 else 0.0

    return BinaryMetrics(
        threshold=threshold,
        target_count=target_count,
        other_count=other_count,
        far=far,
        frr=frr,
    )


def sweep_threshold(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    lo: float = 0.10,
    hi: float = 0.70,
    step: float = 0.025,
) -> List[BinaryMetrics]:
    """扫 threshold 输出 ROC 表。默认 0.10~0.70 步 0.025（与 plan 第 4 节一致）。"""
    points: List[BinaryMetrics] = []
    t = lo
    while t <= hi + 1e-9:
        points.append(binary_metrics(scores, labels, threshold=round(t, 6)))
        t += step
    return points


def eer_threshold(
    scores: Sequence[float], labels: Sequence[int]
) -> Tuple[float, float]:
    """计算 EER 与对应的 threshold。

    EER 定义：FAR == FRR 的工作点。这里用密集 sweep + 最近交叉点的离散近似。
    返回 (eer, threshold)。
    """
    points = sweep_threshold(scores, labels, lo=0.0, hi=1.0, step=0.005)
    best_diff = float("inf")
    best_eer = 0.0
    best_threshold = 0.0
    for p in points:
        diff = abs(p.far - p.frr)
        if diff < best_diff:
            best_diff = diff
            best_eer = (p.far + p.frr) / 2.0
            best_threshold = p.threshold
    return float(best_eer), float(best_threshold)
