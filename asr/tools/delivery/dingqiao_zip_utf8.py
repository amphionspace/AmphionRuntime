#!/usr/bin/env python3
"""Create or patch ZIP archives with UTF-8 filename flag (EFS) for Windows extractors.

APK/AAR inner zips are ASCII-only; delivery zips with 语音识别SDK接口.md need EFS=1.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys
import zipfile
from pathlib import Path


def _zip_info(arcname: str, is_dir: bool) -> zipfile.ZipInfo:
    name = arcname if not is_dir or arcname.endswith("/") else f"{arcname}/"
    info = zipfile.ZipInfo(name)
    info.flag_bits |= 0x800
    info.compress_type = zipfile.ZIP_STORED if is_dir else zipfile.ZIP_DEFLATED
    if is_dir:
        info.external_attr = 0o40755 << 16
    else:
        info.external_attr = 0o100644 << 16
    return info


def zip_tree(source_dir: Path, dest_zip: Path) -> None:
    """Zip directory tree; top-level name in archive = source_dir.name."""
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"[ERROR] not a directory: {source_dir}")

    root_name = source_dir.name
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()

    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(source_dir):
            dirpath_p = Path(dirpath)
            rel_dir = dirpath_p.relative_to(source_dir.parent)
            # directory entry (except implicit root handling)
            if dirpath_p != source_dir.parent:
                arc_dir = rel_dir.as_posix() + "/"
                zf.writestr(_zip_info(arc_dir, True), b"")

            for fname in sorted(filenames):
                fp = dirpath_p / fname
                if fname.startswith("._") or fname == ".DS_Store":
                    continue
                arc = (rel_dir / fname).as_posix()
                info = _zip_info(arc, False)
                zf.writestr(info, fp.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)

    patched = patch_zip_efs(dest_zip)
    verify_zip_utf8(dest_zip, patched=patched)


def patch_zip_efs(path: Path) -> int:
    """Set language encoding flag (bit 11) on all local + central headers."""
    data = bytearray(path.read_bytes())
    i = 0
    patched = 0
    while i < len(data) - 4:
        sig = bytes(data[i : i + 4])
        if sig == b"PK\x03\x04":
            flags = int.from_bytes(data[i + 4 : i + 6], "little")
            if not (flags & 0x800):
                data[i + 4 : i + 6] = (flags | 0x800).to_bytes(2, "little")
                patched += 1
            fn_len = int.from_bytes(data[i + 26 : i + 28], "little")
            extra = int.from_bytes(data[i + 28 : i + 30], "little")
            i += 30 + fn_len + extra
            continue
        if sig == b"PK\x01\x02":
            flags = int.from_bytes(data[i + 8 : i + 10], "little")
            if not (flags & 0x800):
                data[i + 8 : i + 10] = (flags | 0x800).to_bytes(2, "little")
                patched += 1
            fn_len = int.from_bytes(data[i + 28 : i + 30], "little")
            extra = int.from_bytes(data[i + 30 : i + 32], "little")
            comment = int.from_bytes(data[i + 32 : i + 34], "little")
            i += 46 + fn_len + extra + comment
            continue
        i += 1
    path.write_bytes(data)
    return patched


def verify_zip_utf8(path: Path, *, patched: int | None = None) -> None:
    raw = path.read_bytes()
    non_ascii_without_efs: list[str] = []
    i = 0
    while i < len(raw) - 4:
        if raw[i : i + 4] != b"PK\x03\x04":
            i += 1
            continue
        flags = struct.unpack_from("<H", raw, i + 4)[0]
        fn_len = struct.unpack_from("<H", raw, i + 26)[0]
        extra = struct.unpack_from("<H", raw, i + 28)[0]
        fn_bytes = raw[i + 30 : i + 30 + fn_len]
        try:
            fn = fn_bytes.decode("utf-8")
        except UnicodeDecodeError:
            fn = repr(fn_bytes)
        if any(ord(c) > 127 for c in fn) and not (flags & 0x800):
            non_ascii_without_efs.append(fn)
        i += 30 + fn_len + extra

    if non_ascii_without_efs:
        raise SystemExit(
            "[ERROR] ZIP missing UTF-8 EFS on non-ASCII names:\n  "
            + "\n  ".join(non_ascii_without_efs),
        )
    if patched is not None:
        print(f"[OK] UTF-8 ZIP {path} (efs_headers_patched={patched})")
    else:
        print(f"[OK] UTF-8 ZIP verified: {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create ZIP from delivery directory tree")
    p_create.add_argument("source_dir", type=Path)
    p_create.add_argument("dest_zip", type=Path)

    p_patch = sub.add_parser("patch", help="Patch existing ZIP to set EFS on all entries")
    p_patch.add_argument("zip_file", type=Path)

    p_verify = sub.add_parser("verify", help="Verify non-ASCII entries have EFS")
    p_verify.add_argument("zip_file", type=Path)

    args = ap.parse_args(argv)
    if args.cmd == "create":
        zip_tree(args.source_dir, args.dest_zip)
    elif args.cmd == "patch":
        n = patch_zip_efs(args.zip_file)
        verify_zip_utf8(args.zip_file, patched=n)
    else:
        verify_zip_utf8(args.zip_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
