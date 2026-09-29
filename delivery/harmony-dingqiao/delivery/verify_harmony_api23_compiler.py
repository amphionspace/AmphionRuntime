#!/usr/bin/env python3
"""Compile the delivered HAR's TypeScript with the affected API 23 parser."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compile_source(compiler: Path, source: Path, output: Path) -> dict:
    result = subprocess.run(
        [str(compiler), "--module", "--extension", "ts", "--output", str(output), str(source)],
        capture_output=True, text=True, timeout=30,
    )
    return {
        "returncode": result.returncode,
        "abc_generated": output.is_file() and output.stat().st_size > 0,
        "diagnostic": (result.stdout + result.stderr).replace(str(source.parent), "<TEMP>"),
    }


def verify(har: Path, compiler: Path, report: Path) -> dict:
    # Preserve failed evidence as well as successful evidence; callers choose a new path.
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8") as destination:
        result = {"schema_version": 1, "gate": "harmony-api23-compiler", "status": "FAIL", "files": []}
        try:
            result["har_sha256"] = sha256(har)
            result["compiler_sha256"] = sha256(compiler)
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                # A newer compiler accepts the original bug and cannot establish API 23 compatibility.
                probes = {}
                for name in ("unique", "uniqueBoundaries"):
                    source = work / f"{name}.ts"
                    source.write_text(
                        f"const {name} = [0, 1];\n"
                        f"for (let index = 1; index < {name}.length; index++) {{}}\n",
                        encoding="utf-8",
                    )
                    probes[name] = compile_source(compiler, source, work / f"{name}.abc")
                result["compiler_probe"] = probes
                if (probes["unique"]["returncode"] == 0
                        or "Type expected" not in probes["unique"]["diagnostic"]
                        or probes["uniqueBoundaries"]["returncode"] != 0
                        or not probes["uniqueBoundaries"]["abc_generated"]):
                    raise ValueError("compiler does not reproduce the API 23 bug and accept its fix")

                with tarfile.open(har, "r:*") as archive:
                    members = [m for m in archive.getmembers()
                               if m.name.endswith(".ts") and not m.name.endswith(".d.ts")]
                    if not members:
                        raise ValueError("HAR contains no implementation TypeScript files")
                    if len({m.name for m in members}) != len(members):
                        raise ValueError("HAR contains duplicate TypeScript member names")
                    for index, member in enumerate(members):
                        if not member.isfile():
                            raise ValueError(f"TypeScript member is not a regular file: {member.name}")
                        # Never extract archive-controlled paths; the compiler only needs file contents.
                        source = work / f"source-{index}.ts"
                        stream = archive.extractfile(member)
                        assert stream is not None
                        with stream:
                            source.write_bytes(stream.read())
                        compiled = compile_source(compiler, source, work / f"source-{index}.abc")
                        result["files"].append({"path": member.name, "sha256": sha256(source), **compiled})
                if any(f["returncode"] != 0 or not f["abc_generated"] for f in result["files"]):
                    raise ValueError("HAR TypeScript compilation failed; see per-file diagnostics")
            result["status"] = "PASS"
        except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
            # Reports travel with delivery packages; do not persist local user paths in setup errors.
            result["error"] = type(error).__name__ if isinstance(error, OSError) else str(error)
        json.dump(result, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--har", type=Path, required=True)
    parser.add_argument("--es2abc", type=Path, required=True, help="OpenHarmony 6.1 / API 23 es2abc")
    parser.add_argument("--report", type=Path, required=True, help="New output path; never overwritten")
    args = parser.parse_args()
    try:
        result = verify(args.har.resolve(), args.es2abc.resolve(), args.report)
    except OSError as error:
        parser.error(str(error))
    print(f"[{result['status']}] API 23 compiler compatibility: {len(result['files'])} files; {args.report}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
