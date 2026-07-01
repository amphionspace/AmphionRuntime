#!/usr/bin/env python3
"""Generate a Markdown manifest for delivery ZIP artifacts."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ZipArtifact:
    path: Path
    rel_path: str
    kind: str
    size_bytes: int
    sha256: str
    verification_json: str | None
    verification_md: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def detect_kind(path: Path) -> str:
    text = path.as_posix().lower()
    name = path.name.lower()
    if "license" in text:
        return "License"
    if "tts" in text or "lits" in name:
        return "TTS"
    if "asr" in text or "dingqiao" in name or "amphion" in name:
        return "ASR"
    return "Other"


def optional_relative(candidates: list[Path], root: Path) -> str | None:
    for path in candidates:
        if path.exists():
            return path.relative_to(root).as_posix()
    return None


def verification_candidates(zip_path: Path, suffix: str) -> list[Path]:
    stem_path = zip_path.with_suffix("")
    return [
        Path(f"{zip_path}.verification{suffix}"),
        Path(f"{stem_path}.verification{suffix}"),
    ]


def collect_zips(root: Path) -> list[ZipArtifact]:
    artifacts: list[ZipArtifact] = []
    for path in sorted(root.rglob("*.zip")):
        rel = path.relative_to(root).as_posix()
        artifacts.append(
            ZipArtifact(
                path=path,
                rel_path=rel,
                kind=detect_kind(path),
                size_bytes=path.stat().st_size,
                sha256=sha256_file(path),
                verification_json=optional_relative(verification_candidates(path, ".json"), root),
                verification_md=optional_relative(verification_candidates(path, ".md"), root),
            )
        )
    return artifacts


def render_markdown(root: Path, artifacts: list[ZipArtifact], title: str, release_id: str) -> str:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    lines = [
        f"# {title}",
        "",
        f"- Release: `{release_id}`",
        f"- Root: `{root}`",
        f"- Generated: `{generated_at}`",
        "",
        "## ZIP Artifacts",
        "",
    ]
    if not artifacts:
        lines.extend(["No ZIP artifacts found.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "| Type | Path | Size | SHA-256 | Verification |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for artifact in artifacts:
        reports = [p for p in [artifact.verification_md, artifact.verification_json] if p]
        verification = "<br>".join(f"`{p}`" for p in reports) if reports else ""
        lines.append(
            "| {kind} | `{path}` | {size} | `{sha}` | {verification} |".format(
                kind=artifact.kind,
                path=artifact.rel_path,
                size=human_size(artifact.size_bytes),
                sha=artifact.sha256,
                verification=verification,
            )
        )
    lines.extend(["", "## Verification Notes", ""])
    lines.extend(
        [
            "- Treat the final ZIP files listed above as the only customer-facing artifacts.",
            "- Keep verifier JSON / Markdown reports next to the ZIP when available.",
            "- Do not include private keys, `.secure/`, raw SN lists, or local build folders in delivery ZIPs.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("delivery_dir", type=Path, help="Delivery directory to scan")
    parser.add_argument("--output", type=Path, help="Write manifest to this path; stdout when omitted")
    parser.add_argument("--release-id", default="", help="Release identifier, for example 20260701-v3.0")
    parser.add_argument("--title", default="Delivery Manifest", help="Markdown title")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.delivery_dir.resolve()
    if not root.is_dir():
        raise SystemExit(f"delivery_dir is not a directory: {root}")
    release_id = args.release_id or root.name
    markdown = render_markdown(root, collect_zips(root), args.title, release_id)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown + "\n", encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
