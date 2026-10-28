#!/usr/bin/env python3
"""变体交付包的专属校验：模型身份、警务资产裁剪态、包身份。

为什么不复用既有校验：既有校验把基线的模型源包名、完整的警务资产集合都写死为
不变量，那些断言对基线是对的，不该为了让变体过关而放宽 —— 放宽等于让基线从此
不再断言自己的身份。所以变体走这一份独立校验，既有链路一行不改。

与既有校验的分工：
  既有（直接复用，与变体无关）  API 23 编译器兼容性、交付脱敏、打包模型资产、构建身份
  本文件（变体专属）            模型固定策略、警务资产裁剪态、bundleName / 显示名
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

MD5_RE = re.compile(r"[0-9a-f]{32}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
# 端侧载体只接受这一种架构与精度布局：int8 encoder + fp32 decoder/joiner、
# chunk32、left-context 256。版本号由策略文件自己声明，架构不变量在此固定。
SOURCE_BUNDLE_RE = re.compile(
    r"edge-transducer-enc-int8-dec-fp32-join-fp32-chunk32-lc256-\d+\.\d+\.\d+\.tar\.gz"
)
RUNTIME_TO_ONNX_SOURCE = {
    "encoder.int8.ort": "encoder.int8.onnx",
    "decoder.ort": "decoder.onnx",
    "joiner.int8.ort": "joiner.onnx",
}
TRIMMED_VARIANT = "hotwords-only"
TRIMMED_KEEP = {"hotwords.json", "manifest.json"}

HAR_PREFIX = "package/_bundled"
HAR_MODELS = f"{HAR_PREFIX}/amphion_asr/src/main/resources/rawfile/amphion-models"
HAR_POLICE = f"{HAR_PREFIX}/amphion_police/src/main/resources/rawfile/amphion-police"
HAP_MODELS = "resources/rawfile/amphion-models"
HAP_POLICE = "resources/rawfile/amphion-police"


class VariantDeliveryError(RuntimeError):
    pass


class Archive:
    """统一 HAR（tar.gz）与 HAP（zip）的成员读取。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        if path.suffix == ".hap":
            self._zip = zipfile.ZipFile(path)
            self._tar = None
            self.names = set(self._zip.namelist())
        else:
            self._zip = None
            self._tar = tarfile.open(path, "r:*")
            self.names = {m.name for m in self._tar.getmembers() if m.isfile()}

    def read(self, name: str) -> bytes:
        if name not in self.names:
            raise VariantDeliveryError(f"{self.path.name} 缺少成员: {name}")
        if self._zip is not None:
            return self._zip.read(name)
        stream = self._tar.extractfile(name)
        if stream is None:
            raise VariantDeliveryError(f"{self.path.name} 成员不是普通文件: {name}")
        with stream:
            return stream.read()

    def under(self, prefix: str) -> set[str]:
        prefix = prefix.rstrip("/") + "/"
        return {n[len(prefix):] for n in self.names if n.startswith(prefix)}

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
        if self._tar is not None:
            self._tar.close()


def load_policy(path: Path) -> dict:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise VariantDeliveryError(f"无法读取模型固定策略: {path}") from error
    if policy.get("schema_version") != 3:
        raise VariantDeliveryError(f"策略 schema_version 必须为 3: {path}")
    model_id = policy.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise VariantDeliveryError(f"策略缺少 model_id: {path}")
    bundle = policy.get("source_bundle") or {}
    name = bundle.get("name")
    if not isinstance(name, str) or SOURCE_BUNDLE_RE.fullmatch(name) is None:
        raise VariantDeliveryError(f"策略源包名不符合端侧载体架构约定: {name!r}")
    if not isinstance(bundle.get("md5"), str) or MD5_RE.fullmatch(bundle["md5"]) is None:
        raise VariantDeliveryError(f"策略源包 md5 无效: {path}")
    expected = policy.get("onnx_files_md5")
    approved = set(RUNTIME_TO_ONNX_SOURCE.values())
    if not isinstance(expected, dict) or set(expected) != approved:
        raise VariantDeliveryError(
            f"策略 onnx_files_md5 必须恰好覆盖 {sorted(approved)}: {path}")
    for key, digest in expected.items():
        if PurePosixPath(key).name != key or MD5_RE.fullmatch(digest) is None:
            raise VariantDeliveryError(f"策略 onnx_files_md5 条目无效: {key}")
    return policy


def check_model_identity(archive: Archive, prefix: str, policy: dict) -> dict:
    manifest = json.loads(archive.read(f"{prefix}/manifest.json"))
    if manifest.get("manifest_version") != 2:
        raise VariantDeliveryError("模型清单版本必须为 2")
    entries = (manifest.get("bundles") or {}).get("zh-en/v1")
    if not isinstance(entries, list):
        raise VariantDeliveryError("模型清单缺少 zh-en/v1")
    by_name: dict[str, dict] = {}
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str):
            continue
        if name in by_name:
            raise VariantDeliveryError(f"模型清单条目重复: {name}")
        by_name[name] = entry
    expected = policy["onnx_files_md5"]
    for runtime_name, source_name in RUNTIME_TO_ONNX_SOURCE.items():
        entry = by_name.get(runtime_name)
        if entry is None:
            raise VariantDeliveryError(f"模型清单缺少运行时条目: {runtime_name}")
        if entry.get("source_name") != source_name:
            raise VariantDeliveryError(
                f"{runtime_name} 的 source_name 不符: {entry.get('source_name')}")
        if entry.get("source_md5") != expected[source_name]:
            raise VariantDeliveryError(
                f"{source_name} md5 与策略不符: "
                f"{entry.get('source_md5')} != {expected[source_name]}")
    print(f"[OK] 模型身份与策略一致: {policy['model_id']}")
    return {"model_id": policy["model_id"],
            "bundles": sorted(manifest["bundles"]),
            "manifest_sha256": hashlib.sha256(
                archive.read(f"{prefix}/manifest.json")).hexdigest()}


def check_police_trimmed(archive: Archive, prefix: str, source_manifest: dict) -> dict:
    """断言警务资产确为「只留解码期热词表」的裁剪态。

    热词表必须保留且与仓库源逐字节一致 —— 变体仍保留解码期热词偏置，它是该变体
    唯一依赖的警务资产。manifest 本身必然与源不同（files 收窄 + variant 标记），
    故不逐字节比对，而断言它是源 manifest 的合法裁剪。
    """
    packaged = archive.under(prefix)
    if packaged != TRIMMED_KEEP:
        extra = sorted(packaged - TRIMMED_KEEP)
        missing = sorted(TRIMMED_KEEP - packaged)
        raise VariantDeliveryError(
            f"警务资产不是裁剪态: 多出={extra} 缺少={missing}")
    manifest = json.loads(archive.read(f"{prefix}/manifest.json"))
    if manifest.get("variant") != TRIMMED_VARIANT:
        raise VariantDeliveryError(
            f"警务资产 manifest 缺少 variant={TRIMMED_VARIANT} 标记")
    source_hotwords = (source_manifest.get("files") or {}).get("hotwords.json")
    if not isinstance(source_hotwords, str) or SHA256_RE.fullmatch(source_hotwords) is None:
        raise VariantDeliveryError("仓库源 manifest 缺少 hotwords.json 指纹")
    if manifest.get("files") != {"hotwords.json": source_hotwords}:
        raise VariantDeliveryError("裁剪后的 manifest 与源热词表指纹不符")
    actual = hashlib.sha256(archive.read(f"{prefix}/hotwords.json")).hexdigest()
    if actual != source_hotwords:
        raise VariantDeliveryError(f"热词表与仓库源不一致: {actual} != {source_hotwords}")
    counts = manifest.get("hotword_counts") or {}
    print(f"[OK] 警务资产为裁剪态，热词表与源一致（{counts}）")
    return {"variant": TRIMMED_VARIANT, "hotword_counts": counts}


def check_hap_identity(archive: Archive, bundle: str, label: str) -> dict:
    module = json.loads(archive.read("module.json"))
    actual = (module.get("app") or {}).get("bundleName")
    if actual != bundle:
        raise VariantDeliveryError(f"HAP bundleName 不符: {actual} != {bundle}")
    result = {"bundle_name": actual, "module": (module.get("module") or {}).get("name")}
    if label:
        if label.encode("utf-8") not in archive.read("resources.index"):
            raise VariantDeliveryError(f"HAP 资源索引里找不到显示名: {label}")
        result["label"] = label
    print(f"[OK] HAP 身份一致: {actual}" + (f"，显示名「{label}」" if label else ""))
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path, help="变体模型固定策略 JSON")
    parser.add_argument("--police-source", required=True, type=Path,
                        help="仓库里未裁剪的警务资产目录（取 manifest 作为裁剪前基准）")
    parser.add_argument("--har", type=Path, help="自包含 amphion_dingqiao.har")
    parser.add_argument("--hap", type=Path, help="签名 demo HAP")
    parser.add_argument("--expect-bundle", default="", help="期望的 HAP bundleName")
    parser.add_argument("--expect-label", default="", help="期望的 HAP 显示名")
    parser.add_argument("--skip-police-trim", action="store_true",
                        help="该变体保留警务后处理，不做裁剪态断言")
    parser.add_argument("--report", type=Path, help="把校验结果写成 JSON")
    args = parser.parse_args(argv)

    if args.har is None and args.hap is None:
        parser.error("至少要给 --har 或 --hap 之一")

    policy = load_policy(args.policy)
    source_manifest = json.loads(
        (args.police_source / "manifest.json").read_text(encoding="utf-8"))
    report: dict = {"schema_version": 1, "gate": "harmony-variant-delivery",
                    "policy": args.policy.name, "artifacts": {}}
    try:
        for kind, path, model_prefix, police_prefix in (
            ("har", args.har, HAR_MODELS, HAR_POLICE),
            ("hap", args.hap, HAP_MODELS, HAP_POLICE),
        ):
            if path is None:
                continue
            archive = Archive(path)
            try:
                entry = {"name": path.name,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                entry["model"] = check_model_identity(archive, model_prefix, policy)
                if not args.skip_police_trim:
                    entry["police"] = check_police_trimmed(
                        archive, police_prefix, source_manifest)
                if kind == "hap" and args.expect_bundle:
                    entry["identity"] = check_hap_identity(
                        archive, args.expect_bundle, args.expect_label)
                report["artifacts"][kind] = entry
            finally:
                archive.close()
    except VariantDeliveryError as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        if args.report:
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    report["status"] = "PASS"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[PASS] 变体交付校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
