#!/usr/bin/env python3
"""写变体交付包的溯源。

模型身份必须取自本次实际使用的固定策略 —— 取写死的默认策略会让溯源声明基线
模型，而包里装的是另一个，客户拿到的身份信息就是错的。
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--bundle-name", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--police-postprocess", required=True, choices=("on", "off"))
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--build-date", required=True)
    args = parser.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    root, repo = args.package_root, args.repo_root
    artifacts = {}
    for relative in ("release-sdk/har/amphion_dingqiao.har",
                     "diagnostics-demo/dingqiao-demo.hap"):
        path = root / relative
        if path.is_file():
            artifacts[relative] = {"sha256": sha256(path), "size_bytes": path.stat().st_size}

    patches = sorted((repo / "third_party/patches/sherpa-amphion").glob("*.patch"))
    series = hashlib.sha256()
    for patch in patches:
        series.update(patch.read_bytes())

    provenance = {
        "schema_version": 1,
        "delivery_kind": "variant",
        "variant": args.variant,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "build_date": args.build_date,
        "source": {
            "commit": args.source_commit,
            "branch": git(repo, "branch", "--show-current"),
            "sherpa_submodule_commit": git(repo, "rev-parse", "HEAD:third_party/sherpa-onnx"),
            "sherpa_patch_count": len(patches),
            "sherpa_patch_series_sha256": series.hexdigest(),
        },
        "model": {
            "model_id": policy["model_id"],
            "model_md5_policy": args.policy.name,
            "onnx_md5": dict(sorted(policy["onnx_files_md5"].items())),
            "source_bundle": policy.get("source_bundle", {}),
        },
        "package_identity": {
            "bundle_name": args.bundle_name,
            "app_label": args.label,
            "police_postprocess": args.police_postprocess,
        },
        "artifacts": artifacts,
    }
    out = root / "docs/BUILD_PROVENANCE.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"[OK] 溯源已写入: model_id={policy['model_id']} "
          f"bundle={args.bundle_name} police={args.police_postprocess}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
