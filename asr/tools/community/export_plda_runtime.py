#!/usr/bin/env python3
"""Convert Community-1 x-vector/PLDA parameters to a fixed little-endian blob."""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path

import numpy as np
from scipy.linalg import eigh


MAGIC = b"C1PLDA01"
VERSION = 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xvec_transform", type=Path)
    parser.add_argument("plda", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    xvec = np.load(args.xvec_transform)
    plda = np.load(args.plda)
    mean1 = np.asarray(xvec["mean1"], dtype="<f4")
    mean2 = np.asarray(xvec["mean2"], dtype="<f4")
    lda = np.asarray(xvec["lda"], dtype="<f4")
    mu = np.asarray(plda["mu"], dtype="<f4")
    source_tr = np.asarray(plda["tr"], dtype=np.float64)
    source_psi = np.asarray(plda["psi"], dtype=np.float64)

    if mean1.shape != (256,) or mean2.shape != (128,) or lda.shape != (256, 128):
        raise ValueError("unexpected Community-1 x-vector transform shape")
    if mu.shape != (128,) or source_tr.shape != (128, 128) or source_psi.shape != (128,):
        raise ValueError("unexpected Community-1 PLDA shape")

    # Keep this identical to pyannote.audio.utils.vbx.vbx_setup.
    within = np.linalg.inv(source_tr.T @ source_tr)
    between = np.linalg.inv((source_tr.T / source_psi) @ source_tr)
    eigenvalues, eigenvectors = eigh(between, within)
    phi = np.asarray(eigenvalues[::-1], dtype="<f4")
    transform = np.asarray(eigenvectors.T[::-1], dtype="<f4")

    arrays = (mean1, lda, mean2, mu, transform, phi)
    payload = bytearray(MAGIC)
    payload.extend(struct.pack("<III", VERSION, 256, 128))
    for array in arrays:
        payload.extend(np.ascontiguousarray(array).tobytes())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    print(f"wrote {args.output} ({len(payload)} bytes, sha256={digest})")


if __name__ == "__main__":
    main()
