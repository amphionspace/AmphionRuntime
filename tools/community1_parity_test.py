#!/usr/bin/env python3
"""Fixed-input parity check for Community-1 clustering.

The Harmony native module accepts already extracted embeddings and masks, so
this test isolates the PLDA/AHC/VBx boundary.  Run the native fixture on a
device (or through a small NAPI harness), save the returned object as JSON,
then pass it with --native-json.  The script deliberately uses float64 for
the reference and reports tolerances separately from exact integer labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLDA = ROOT / "shared" / "models" / "asr" / "dingqiao" / "community1-plda.npz"
EMBEDDING_DIM = 256
PLDA_DIM = 128
LOCAL_SPEAKERS = 3
FRAMES = 589
FA = 0.07
FB = 0.8
AHC_DISTANCE_THRESHOLD = 0.6
PI_FLOOR = 1e-7


def fixture() -> tuple[np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(20260925)
    chunks = 4
    prototypes = rng.normal(size=(LOCAL_SPEAKERS, EMBEDDING_DIM))
    prototypes /= np.linalg.norm(prototypes, axis=1, keepdims=True)
    embeddings = np.full((chunks, LOCAL_SPEAKERS, EMBEDDING_DIM), np.nan, dtype=np.float64)
    masks = np.zeros((chunks, FRAMES), dtype=np.int32)
    for chunk in range(chunks):
        for local in range(LOCAL_SPEAKERS):
            # Every channel gets enough clean frames for the native validity
            # rule, with a deterministic local-to-global permutation.
            mask = 1 << local
            begin = 20 + local * 150
            masks[chunk, begin:begin + 160] = mask
            global_speaker = (local + (chunk // 2)) % LOCAL_SPEAKERS
            embeddings[chunk, local] = (
                prototypes[global_speaker] + 0.025 * rng.normal(size=EMBEDDING_DIM)
            )
    return embeddings.reshape(-1, EMBEDDING_DIM), masks.reshape(-1), chunks


def load_plda(path: Path) -> dict[str, np.ndarray]:
    values = np.load(path)
    required = {"mu", "tr", "psi"}
    if not required.issubset(values.files):
        raise ValueError(f"PLDA file is missing {required - set(values.files)}")
    xvec_path = path.with_name("community1-xvec-transform.npz")
    if not xvec_path.exists():
        # The source distribution stores the x-vector transform beside PLDA.
        xvec_path = ROOT / "shared" / "models" / "asr" / "dingqiao" / "community1-xvec-transform.npz"
    xvec = np.load(xvec_path)
    return {
        "mu": values["mu"].astype(np.float64),
        "tr": values["tr"].astype(np.float64),
        "psi": values["psi"].astype(np.float64),
        "mean1": xvec["mean1"].astype(np.float64),
        "mean2": xvec["mean2"].astype(np.float64),
        "lda": xvec["lda"].astype(np.float64),
    }


def transform(embeddings: np.ndarray, plda: dict[str, np.ndarray]) -> np.ndarray:
    centered = embeddings - plda["mean1"]
    centered *= np.sqrt(EMBEDDING_DIM) / np.maximum(np.linalg.norm(centered, axis=1, keepdims=True), 1e-20)
    xvec = centered @ plda["lda"] - plda["mean2"]
    xvec *= np.sqrt(PLDA_DIM) / np.maximum(np.linalg.norm(xvec, axis=1, keepdims=True), 1e-20)
    return (xvec - plda["mu"]) @ plda["tr"].T


def ahc(embeddings: np.ndarray) -> np.ndarray:
    rows = len(embeddings)
    if rows <= 1:
        return np.zeros(rows, dtype=np.int32)
    # Community-1 uses scipy linkage(method="centroid", metric="euclidean")
    # on L2-normalized input rows. Merged centroids are not re-normalized.
    centroids = [row / max(np.linalg.norm(row), 1e-20) for row in embeddings]
    sizes = [1] * rows
    children: list[tuple[int, int] | None] = [None] * rows
    max_distance = [0.0] * rows
    active = list(range(rows))
    while len(active) > 1:
        best = (0, 1)
        best_distance = np.inf
        for left in range(len(active)):
            for right in range(left + 1, len(active)):
                delta = centroids[active[left]] - centroids[active[right]]
                distance = float(np.sqrt(np.dot(delta, delta)))
                if distance < best_distance:
                    best_distance = distance
                    best = (left, right)
        left_id, right_id = active[best[0]], active[best[1]]
        node = len(centroids)
        merged = ((sizes[left_id] * centroids[left_id] + sizes[right_id] * centroids[right_id]) /
                  (sizes[left_id] + sizes[right_id]))
        centroids.append(merged)
        sizes.append(sizes[left_id] + sizes[right_id])
        children.append((left_id, right_id))
        max_distance.append(max(best_distance, max_distance[left_id], max_distance[right_id]))
        active[best[0]] = node
        active.pop(best[1])

    labels = np.full(rows, -1, dtype=np.int32)
    next_label = 0

    def assign(node: int) -> None:
        nonlocal next_label
        if node < rows:
            labels[node] = next_label
            next_label += 1
        elif max_distance[node] <= AHC_DISTANCE_THRESHOLD:
            stack = [node]
            label = next_label
            next_label += 1
            while stack:
                current = stack.pop()
                if current < rows:
                    labels[current] = label
                else:
                    assert children[current] is not None
                    stack.extend(children[current])
        else:
            assert children[node] is not None
            assign(children[node][0])
            assign(children[node][1])

    assign(active[0])
    return labels


def logsumexp(values: np.ndarray, axis: int) -> np.ndarray:
    maximum = np.max(values, axis=axis, keepdims=True)
    return np.squeeze(maximum, axis=axis) + np.log(np.maximum(np.sum(np.exp(values - maximum), axis=axis), 1e-30))


def vbx(ahc_labels: np.ndarray, features: np.ndarray, phi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    speakers = int(np.max(ahc_labels)) + 1
    rows = len(features)
    high = np.exp(7.0)
    gamma = np.where(
        ahc_labels[:, None] == np.arange(speakers)[None, :], high, 1.0
    ) / (high + speakers - 1)
    priors = np.full(speakers, 1.0 / speakers)
    rho = features * np.sqrt(phi)[None, :]
    gaussian = -0.5 * (np.sum(features * features, axis=1) + PLDA_DIM * np.log(2.0 * np.pi))
    inv_l = np.zeros((speakers, PLDA_DIM))
    alpha = np.zeros((speakers, PLDA_DIM))
    previous = -np.inf
    scale = FA / FB
    for _ in range(20):
        for speaker in range(speakers):
            count = np.sum(gamma[:, speaker])
            sufficient = np.sum(gamma[:, speaker, None] * rho, axis=0)
            inv_l[speaker] = 1.0 / (1.0 + scale * count * phi)
            alpha[speaker] = scale * inv_l[speaker] * sufficient
        linear = rho @ alpha.T
        quadratic = np.sum((inv_l[None, :, :] + alpha[None, :, :] ** 2) * phi[None, None, :], axis=2)
        log_probability = FA * (linear - 0.5 * quadratic + gaussian[:, None]) + np.log(priors[None, :] + 1e-8)
        normalizer = logsumexp(log_probability, axis=1)
        gamma = np.exp(log_probability - normalizer[:, None])
        priors = np.mean(gamma, axis=0)
        regularizer = np.sum(np.log(inv_l) - inv_l - alpha * alpha + 1.0)
        elbo = float(np.sum(normalizer) + FB * 0.5 * regularizer)
        if elbo - previous < 1e-4:
            break
        previous = elbo
    return gamma, priors


def reference(plda_path: Path) -> dict[str, Any]:
    embeddings, masks, chunks = fixture()
    valid: list[int] = []
    for chunk in range(chunks):
        for local in range(LOCAL_SPEAKERS):
            clean = np.count_nonzero(masks[chunk * FRAMES:(chunk + 1) * FRAMES] == (1 << local))
            row = chunk * LOCAL_SPEAKERS + local
            if clean >= int(np.ceil(0.2 * FRAMES)) and np.isfinite(embeddings[row]).all():
                valid.append(row)
    train = embeddings[valid]
    labels = ahc(train)
    features = transform(train, load_plda(plda_path))
    responsibilities, priors = vbx(labels, features, load_plda(plda_path)["psi"])
    retained = [i for i, prior in enumerate(priors) if prior > PI_FLOOR]
    centroids = []
    for speaker in retained:
        weights = responsibilities[:, speaker]
        centroid = np.sum(weights[:, None] * train, axis=0) / max(float(np.sum(weights)), 1e-20)
        centroids.append(centroid)
    centroids = np.asarray(centroids)
    scores = np.full((chunks * LOCAL_SPEAKERS, len(retained)), -1e30, dtype=np.float64)
    hard = np.full(chunks * LOCAL_SPEAKERS, -2, dtype=np.int32)
    for row in range(chunks * LOCAL_SPEAKERS):
        if not np.isfinite(embeddings[row]).all() or not len(retained):
            continue
        sample = embeddings[row] / max(np.linalg.norm(embeddings[row]), 1e-20)
        centers = centroids / np.maximum(np.linalg.norm(centroids, axis=1, keepdims=True), 1e-20)
        scores[row] = 1.0 + centers @ sample
        hard[row] = int(np.argmax(scores[row]))
    return {
        "hardClusters": hard.tolist(),
        "clusterScores": scores.reshape(-1).tolist(),
        "speakerCount": len(retained),
        "constraintViolated": False,
        "fixture": {
            "seed": 20260925,
            "chunks": chunks,
            "embeddingsShape": list(embeddings.shape),
            "masksShape": list(masks.shape),
            "plda": str(plda_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plda", type=Path, default=DEFAULT_PLDA)
    parser.add_argument("--native-json", type=Path)
    parser.add_argument("--print-reference", action="store_true")
    args = parser.parse_args()
    expected = reference(args.plda)
    if args.print_reference or args.native_json is None:
        print(json.dumps(expected, ensure_ascii=False, indent=2))
    if args.native_json is None:
        return 0
    actual = json.loads(args.native_json.read_text(encoding="utf-8"))
    if actual.get("hardClusters") != expected["hardClusters"]:
        raise SystemExit("hardClusters mismatch")
    expected_scores = np.asarray(expected["clusterScores"], dtype=np.float64)
    actual_scores = np.asarray(actual.get("clusterScores", []), dtype=np.float64)
    if actual_scores.shape != expected_scores.shape or not np.allclose(actual_scores, expected_scores, atol=2e-3, rtol=2e-3):
        raise SystemExit("clusterScores mismatch")
    if int(actual.get("speakerCount", -1)) != expected["speakerCount"]:
        raise SystemExit("speakerCount mismatch")
    print("Community-1 native parity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
