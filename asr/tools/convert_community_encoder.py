#!/usr/bin/env python3
"""Convert the pinned Community encoder to verified MindSpore Lite .ms bytes.

Offline Linux x86_64 preparation, not NPU or accuracy acceptance. Example:
  .venv-harmony-ort-1.16.3/bin/python asr/tools/convert_community_encoder.py \
    --package mindspore-lite-2.7.0-linux-x64.tar.gz \
    --output .cache/community-encoder-mindir/community-wespeaker-encoder.fp16.ms

--inspect checks source/package identity without executing Linux binaries.
--verify audits an existing pair with a host C++ compiler and the package's
header-only FlatBuffers verifier, including on macOS. Dependencies are never
downloaded. Conversion always runs one synthetic CPU inference. --fp16=on only
requests FP16 constant storage, not FP16 execution of every NPU operator.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "shared/models/asr/dingqiao/community-wespeaker-encoder.fp32.onnx"
DEFAULT_PACKAGE = ROOT / "mindspore-lite-2.7.0-linux-x64.tar.gz"
DEFAULT_CACHE = ROOT / ".cache/community-encoder-mindir"
PACKAGE_DIRECTORY = "mindspore-lite-2.7.0-linux-x64"
EXPECTED_PACKAGE_SHA256 = "8bb1097100c9fec12675670ba2d4264a2cd6da3a9be093eb56631d00fc0c455b"
EXPECTED_PACKAGE_BYTES = 66_063_055
EXPECTED_SOURCE_SHA256 = "8f8c4619237d023770f5ed18012123771e216c5ec358987b8d3c4e486a74d30f"
EXPECTED_SOURCE_BYTES = 21_301_300
EXPECTED_VERSION = "2.7.0"
EXPECTED_SIGNATURE = {
    "inputs": [{"name": "fbank", "dtype": "FLOAT", "shape": [1, 998, 80]}],
    "outputs": [{"name": "/resnet/pool/Reshape_output_0", "dtype": "FLOAT",
                 "shape": [1, 2560, 125]}],
}
CONVERTER = "tools/converter/converter/converter_lite"
BENCHMARK = "tools/benchmark/benchmark"
SCHEMA = "tools/converter/include/schema/model_generated.h"
# Independently inspected archive members, also usable by dependency-free audits.
EXPECTED_COMPONENTS = {
    CONVERTER: {"file": "converter_lite", "sizeBytes": 412_688,
                "sha256": "d10fe9b20a368e02ce4278ad111010a1b4c62b1e4334a2f4003d64470894e035"},
    BENCHMARK: {"file": "benchmark", "sizeBytes": 728_136,
                "sha256": "5293e6739d375184fd11cdbbb4daad3d7d1132d891c4b08cfeed3e2ecff14b7d"},
    SCHEMA: {"file": "model_generated.h", "sizeBytes": 122_148,
             "sha256": "e9bdb94cfe6a6b5c1a008bfd1c33e66ebe582b59cb12d0b9bfb223e18b53eab1"},
}
CONVERSION_FLAGS = [
    "--fmk=ONNX", "--saveType=MINDIR_LITE", "--fp16=on",
    "--inputDataType=FLOAT", "--outputDataType=FLOAT",
    "--inputShape=fbank:1,998,80", "--optimize=general", "--infer=false",
    "--trainModel=false", "--optimizeTransformer=false",
]
BENCHMARK_FLAGS = [
    "--modelType=MindIR_Lite", "--device=CPU", "--loopCount=1",
    "--warmUpLoopCount=0", "--numThreads=1", "--enableFp16=false",
]
PRECISION_SCOPE = (
    "fp16=on serializes eligible FP32 constants as FP16; public I/O stays FP32. "
    "It does not prove FP16 execution or placement of every NPU operator."
)
VALIDATION_SCOPE = (
    "FlatBuffer structure/signature verification and one synthetic CPU inference "
    "only; not real audio, numerical parity, speaker accuracy, performance or NPU acceptance."
)

# Compiled for the host; never linked to the package's Linux shared libraries.
SCHEMA_VERIFIER_CPP = r'''
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <vector>
#include "schema/model_generated.h"
#include "api/data_type.h"

namespace s = mindspore::schema;
std::string quote(const std::string &text) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : text) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c < 32 || c >= 127)
      out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
    else out << c;
  }
  out << '"';
  return out.str();
}
void indices(const flatbuffers::Vector<uint32_t> *v, size_t count) {
  if (!v) throw std::runtime_error("missing tensor indices");
  for (auto i : *v) if (i >= count) throw std::runtime_error("tensor index out of bounds");
}
void signature(const s::MetaGraph *g, const flatbuffers::Vector<uint32_t> *v) {
  indices(v, g->allTensors()->size());
  std::cout << '[';
  bool first = true;
  for (auto i : *v) {
    auto t = g->allTensors()->Get(i);
    if (!t || !t->name() || !t->dims()) throw std::runtime_error("missing I/O signature");
    if (!first) std::cout << ',';
    first = false;
    const char *dtype = t->dataType() == int(mindspore::DataType::kNumberTypeFloat32)
                            ? "FLOAT" : "NON_FP32";
    std::cout << "{\"name\":" << quote(t->name()->str())
              << ",\"dtype\":" << quote(dtype) << ",\"shape\":[";
    for (size_t j = 0; j < t->dims()->size(); ++j) {
      if (j) std::cout << ',';
      std::cout << t->dims()->Get(j);
    }
    std::cout << "]}";
  }
  std::cout << ']';
}
int main(int argc, char **argv) {
  try {
    if (argc != 2) throw std::runtime_error("expected model path");
    std::ifstream in(argv[1], std::ios::binary);
    if (!in) throw std::runtime_error("cannot open model");
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(in)), {});
    if (data.size() < 8) throw std::runtime_error("truncated FlatBuffer");
    flatbuffers::Verifier verifier(data.data(), data.size());
    if (!s::VerifyMetaGraphBuffer(verifier))
      throw std::runtime_error("VerifyMetaGraphBuffer failed (expected MSL2 Lite format)");
    auto g = s::GetMetaGraph(data.data());
    if (!g->version() || !g->allTensors() || !g->nodes() || !g->nodes()->size())
      throw std::runtime_error("missing graph version/tensors/nodes");
    if (g->obfuscate()) throw std::runtime_error("obfuscated graph is not supported");
    size_t fp16 = 0, external = 0;
    for (auto t : *g->allTensors()) {
      if (t->externalData() && t->externalData()->size()) ++external;
      if (t->dataType() == int(mindspore::DataType::kNumberTypeFloat16) &&
          t->data() && t->data()->size()) ++fp16;
    }
    for (auto n : *g->nodes()) {
      if (!n->primitive()) throw std::runtime_error("missing node primitive");
      indices(n->inputIndex(), g->allTensors()->size());
      indices(n->outputIndex(), g->allTensors()->size());
    }
    std::cout << "{\"identifier\":" << quote(s::MetaGraphIdentifier())
              << ",\"version\":" << quote(g->version()->str())
              << ",\"tensorCount\":" << g->allTensors()->size()
              << ",\"nodeCount\":" << g->nodes()->size()
              << ",\"storedFloat16TensorCount\":" << fp16
              << ",\"externalDataTensorCount\":" << external << ",\"inputs\":";
    signature(g, g->inputIndex());
    std::cout << ",\"outputs\":";
    signature(g, g->outputIndex());
    std::cout << "}\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
'''


class ConversionError(RuntimeError):
    pass


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ConversionError(f"missing regular file (symlinks are not accepted): {path}")
    with path.open("rb") as stream:
        digest = sha256_stream(stream)
    return {"file": path.name, "sizeBytes": path.stat().st_size, "sha256": digest}


def require_linux() -> None:
    system, machine = platform.system(), platform.machine()
    if system != "Linux" or machine.lower() not in ("x86_64", "amd64"):
        raise ConversionError(
            f"conversion requires Linux x86_64/amd64, found {system} {machine}; "
            "use --inspect or --verify on macOS. No Linux binary was executed."
        )


def inspect_source(source: Path) -> dict:
    identity = file_identity(source)
    if identity["sha256"] != EXPECTED_SOURCE_SHA256 or identity["sizeBytes"] != EXPECTED_SOURCE_BYTES:
        raise ConversionError(f"FP32 source identity mismatch: {identity}")
    try:
        import onnx
    except ImportError as error:
        raise ConversionError(
            "missing ONNX structural parser; use the existing "
            ".venv-harmony-ort-1.16.3/bin/python (onnx==1.15.0), "
            "or a pre-provisioned Linux environment with onnx. Nothing is installed automatically."
        ) from error
    try:
        model = onnx.load(str(source), load_external_data=False)
        onnx.checker.check_model(model)
        if any(t.data_location == onnx.TensorProto.EXTERNAL for t in model.graph.initializer):
            raise ConversionError("external ONNX tensor data is not accepted")

        def tensor(value) -> dict:
            spec = value.type.tensor_type
            if not spec.HasField("shape") or any(not d.HasField("dim_value") for d in spec.shape.dim):
                raise ConversionError(f"dynamic/missing ONNX shape: {value.name}")
            return {"name": value.name, "dtype": onnx.TensorProto.DataType.Name(spec.elem_type),
                    "shape": [d.dim_value for d in spec.shape.dim]}

        signature = {"inputs": [tensor(v) for v in model.graph.input],
                     "outputs": [tensor(v) for v in model.graph.output]}
        opsets = [{"domain": item.domain, "version": item.version} for item in model.opset_import]
        counts = dict(sorted(Counter(n.op_type for n in model.graph.node).items()))
        if signature != EXPECTED_SIGNATURE:
            raise ConversionError(f"ONNX I/O signature mismatch: {signature}")
        if opsets != [{"domain": "", "version": 17}]:
            raise ConversionError(f"expected ONNX opset 17, found {opsets}")
        if counts.get("Conv") != 36 or "LSTM" in counts or "If" in counts:
            raise ConversionError(f"unexpected ONNX graph operators: {counts}")
    except ConversionError:
        raise
    except Exception as error:
        raise ConversionError(f"ONNX structural validation failed: {error}") from error
    return {**identity, "format": "ONNX", "signature": signature, "opsets": opsets,
            "operatorCounts": counts, "onnxVersion": onnx.__version__}


def package_members(archive: tarfile.TarFile) -> list:
    members = archive.getmembers()
    names = set()
    for item in members:
        path = PurePosixPath(item.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != PACKAGE_DIRECTORY:
            raise ConversionError(f"unsafe/unexpected package member: {item.name}")
        if item.name in names or not (item.isfile() or item.isdir()):
            raise ConversionError(f"duplicate or non-regular package member: {item.name}")
        names.add(item.name)
    return members


@contextmanager
def prepared_package(package: Path, converter_root: Path | None, cache: Path):
    identity = file_identity(package)
    if identity["sha256"] != EXPECTED_PACKAGE_SHA256 or identity["sizeBytes"] != EXPECTED_PACKAGE_BYTES:
        raise ConversionError(f"Lite package SHA-256 mismatch: {identity['sha256']}")
    temporary = None
    try:
        with tarfile.open(package, "r:gz") as archive:
            members = package_members(archive)
            if converter_root is None:
                cache.mkdir(parents=True, exist_ok=True)
                temporary = tempfile.TemporaryDirectory(prefix="package-", dir=cache)
                archive.extractall(temporary.name, members=members)
                converter_root = Path(temporary.name) / PACKAGE_DIRECTORY
            root = converter_root.resolve()
            expected = {}
            for item in members:
                if not item.isfile():
                    continue
                relative = PurePosixPath(item.name).relative_to(PACKAGE_DIRECTORY).as_posix()
                with archive.extractfile(item) as stream:
                    expected[relative] = {"sizeBytes": item.size, "sha256": sha256_stream(stream)}
            actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*")
                            if not p.is_dir() or p.is_symlink()}
            if actual_paths != set(expected):
                raise ConversionError("converter-root files differ from the pinned package inventory")
            for relative, spec in expected.items():
                path = root / relative
                if not path.resolve().is_relative_to(root):
                    raise ConversionError(f"package member escapes converter-root: {relative}")
                actual = file_identity(path)
                if actual["sha256"] != spec["sha256"] or actual["sizeBytes"] != spec["sizeBytes"]:
                    raise ConversionError(f"converter-root member differs from package: {relative}")
            for required in (CONVERTER, BENCHMARK, SCHEMA, "tools/converter/include/api/data_type.h"):
                if required not in expected:
                    raise ConversionError(f"missing Lite package member: {required}")
            for relative, spec in EXPECTED_COMPONENTS.items():
                if file_identity(root / relative) != spec:
                    raise ConversionError(f"pinned Lite component identity mismatch: {relative}")
            inventory_digest = hashlib.sha256(
                json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            record = {**identity, "version": EXPECTED_VERSION, "platform": "linux-x86_64",
                      "inventorySha256": inventory_digest, "verifiedFileCount": len(expected)}
            yield root, record
    except (tarfile.TarError, OSError) as error:
        raise ConversionError(f"cannot inspect local Lite package: {error}") from error
    finally:
        if temporary is not None:
            temporary.cleanup()


def tool_environment(root: Path, directory: Path) -> dict[str, str]:
    library_dirs = [root / "tools/converter/lib", root / "runtime/lib"]
    library_dirs += sorted({p.parent for p in (root / "runtime/third_party").rglob("*.so*")})
    # Do not inherit LD_PRELOAD, external libraries, MS_* settings or converter flags.
    return {"PATH": os.defpath, "HOME": str(directory), "TMPDIR": str(directory),
            "LANG": "C", "LC_ALL": "C",
            "LD_LIBRARY_PATH": os.pathsep.join(str(p) for p in library_dirs)}


def run_tool(argv: list[str], directory: Path, env: dict, label: str, timeout: int = 600) -> dict:
    try:
        result = subprocess.run(argv, cwd=directory, env=env, capture_output=True,
                                text=True, errors="replace", timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else (value or "")

        (directory / f"{label}.json").write_text(json.dumps({
            "argv": argv, "status": "TIMEOUT", "stdout": text(error.stdout), "stderr": text(error.stderr),
        }, indent=2) + "\n", encoding="utf-8")
        raise ConversionError(f"{label} timed out after {timeout}s; logs: {directory}") from error
    except OSError as error:
        (directory / f"{label}.error.log").write_text(str(error) + "\n", encoding="utf-8")
        raise ConversionError(f"{label} could not run: {error}; logs: {directory}") from error
    record = {"argv": argv, "returnCode": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr}
    (directory / f"{label}.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if result.returncode != 0:
        raise ConversionError(f"{label} failed with exit {result.returncode}; logs: {directory}")
    return record


def checked_help(tool: Path, flags: list[str], directory: Path, env: dict, label: str) -> dict:
    record = run_tool([str(tool), "--help"], directory, env, label, timeout=30)
    text = record["stdout"] + record["stderr"]
    missing = [flag.split("=", 1)[0] for flag in flags if flag.split("=", 1)[0] not in text]
    if missing:
        raise ConversionError(f"{tool.name} help does not advertise required flags: {missing}")
    return record


def validate_mindir_signature(signature: dict) -> None:
    if signature.get("identifier") != "MSL2":
        raise ConversionError("expected MSL2 FlatBuffer identifier (MINDIR_LITE), not a filename claim")
    versions = re.findall(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", signature.get("version", ""))
    if versions != [EXPECTED_VERSION]:
        raise ConversionError(f"unexpected Lite model version: {signature.get('version')}")
    if {key: signature.get(key) for key in EXPECTED_SIGNATURE} != EXPECTED_SIGNATURE:
        raise ConversionError(f"Lite FP32 I/O signature mismatch: {signature}")
    if signature.get("externalDataTensorCount") != 0:
        raise ConversionError("external Lite tensor data is not accepted; output must be self-contained")
    if signature.get("storedFloat16TensorCount", 0) < 1:
        raise ConversionError("fp16=on did not produce any stored FP16 constant tensor")
    if signature.get("nodeCount", 0) < 1 or signature.get("tensorCount", 0) < 2:
        raise ConversionError("Lite graph has no nodes/tensors")


def schema_signature(output: Path, root: Path, directory: Path, cxx: str | None = None) -> dict:
    compiler = cxx or shutil.which("c++", path=os.defpath)
    if not compiler:
        raise ConversionError("host C++ compiler is required for package-schema verification; use --cxx")
    compiler = shutil.which(compiler, path=os.defpath) or compiler
    source, executable = directory / "verify_mindir.cpp", directory / "verify_mindir"
    source.write_text(SCHEMA_VERIFIER_CPP, encoding="utf-8")
    include = root / "tools/converter/include"
    env = {"PATH": os.defpath, "HOME": str(directory), "TMPDIR": str(directory), "LC_ALL": "C"}
    compile_result = run_tool([compiler, "-std=c++11", "-O0", f"-I{include}",
                               f"-I{include / 'third_party'}", str(source), "-o", str(executable)],
                              directory, env, "schema-compile", timeout=120)
    result = run_tool([str(executable), str(output)], directory, env, "schema-verify", timeout=30)
    try:
        signature = json.loads(result["stdout"])
        validate_mindir_signature(signature)
    except (json.JSONDecodeError, TypeError, AttributeError) as error:
        raise ConversionError("package-schema verifier did not return a valid JSON signature") from error
    return {"method": "package-schema VerifyMetaGraphBuffer", "status": "PASS", "model": signature,
            "schema": file_identity(root / SCHEMA),
            "helperSourceSha256": hashlib.sha256(SCHEMA_VERIFIER_CPP.encode()).hexdigest(),
            "compile": compile_result, "execution": result}


def converter_identity(root: Path) -> dict:
    return {**file_identity(root / CONVERTER), "version": EXPECTED_VERSION,
            "versionEvidence": "executable is byte-identical to the SHA-256 pinned 2.7.0 archive member; "
                               "the converter CLI does not advertise a --version flag"}


def provenance_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".provenance.json")


def check_destinations(output: Path) -> None:
    if output.suffix != ".ms":
        raise ConversionError("output must use the explicit Lite .ms extension")
    for path in (output, provenance_path(output)):
        if os.path.lexists(path):
            raise ConversionError(f"refusing to overwrite existing output/evidence: {path}")


def publish_pair(candidate: Path, evidence: Path, output: Path) -> None:
    check_destinations(output)
    linked = False
    try:
        # Hard links provide an atomic, no-clobber publish on the same filesystem.
        os.link(candidate, output)
        linked = True
        os.link(evidence, provenance_path(output))
    except OSError as error:
        if linked and os.path.lexists(output) and os.path.samestat(candidate.stat(), output.lstat()):
            output.unlink()
        raise ConversionError(f"cannot publish model/provenance without overwriting: {error}") from error


def synthetic_input_record() -> dict:
    return {"file": "synthetic-zero-fbank.f32", "sizeBytes": 998 * 80 * 4,
            "sha256": hashlib.sha256(bytes(998 * 80 * 4)).hexdigest(),
            **EXPECTED_SIGNATURE["inputs"][0], "kind": "synthetic-all-zero",
            "encoding": "little-endian IEEE-754 float32", "finite": True,
            "min": 0.0, "max": 0.0, "realAudio": False, "realFbank": False}


def execution_flags(step: dict, executable: str, flags: list[str], files: dict[str, str]) -> None:
    argv = step["argv"]
    if not argv or Path(argv[0]).name != executable or step["returnCode"] != 0:
        raise ConversionError(f"provenance lacks successful {executable} execution")
    if argv[1:1 + len(flags)] != flags or len(argv) != 1 + len(flags) + len(files):
        raise ConversionError(f"provenance actual {executable} argv differs from the fixed recipe")
    for arg, (flag, name) in zip(argv[1 + len(flags):], files.items()):
        prefix = flag + "="
        if not arg.startswith(prefix) or Path(arg[len(prefix):]).name != name:
            raise ConversionError(f"provenance {executable} file argument mismatch: {flag}")


def verify_provenance(output: Path, source: Path = DEFAULT_SOURCE) -> dict:
    """Standard-library audit for packaging; never execute commands from evidence."""
    source_identity, output_identity = file_identity(source), file_identity(output)
    if source_identity["sha256"] != EXPECTED_SOURCE_SHA256 or source_identity["sizeBytes"] != EXPECTED_SOURCE_BYTES:
        raise ConversionError("FP32 source identity mismatch")
    with output.open("rb") as stream:
        if stream.read(8)[4:8] != b"MSL2":
            raise ConversionError("model is not a MSL2 Lite FlatBuffer")
    try:
        record = json.loads(provenance_path(output).read_text(encoding="utf-8"))
        if (record["schemaVersion"], record["kind"], record["status"]) != (1, "community-encoder-mindir", "VERIFIED"):
            raise ConversionError("unsupported/incomplete provenance")
        src = record["source"]
        if any(src[key] != value for key, value in source_identity.items()):
            raise ConversionError("provenance/source mismatch")
        if (src["format"] != "ONNX" or src["signature"] != EXPECTED_SIGNATURE or
                src["opsets"] != [{"domain": "", "version": 17}] or src["operatorCounts"].get("Conv") != 36 or
                any(op in src["operatorCounts"] for op in ("If", "LSTM"))):
            raise ConversionError("provenance source graph/signature mismatch")
        if record["output"] != {**output_identity, "format": "MINDIR_LITE", "signature": EXPECTED_SIGNATURE}:
            raise ConversionError("provenance/output hash, bytes, format or signature mismatch")
        if (record["package"]["sha256"] != EXPECTED_PACKAGE_SHA256 or
                record["package"]["sizeBytes"] != EXPECTED_PACKAGE_BYTES or
                record["package"]["platform"] != "linux-x86_64" or
                record["package"]["version"] != EXPECTED_VERSION or record["converter"]["version"] != EXPECTED_VERSION or
                any(record["converter"][k] != v for k, v in EXPECTED_COMPONENTS[CONVERTER].items())):
            raise ConversionError("provenance package/converter identity mismatch")
        conversion, validation = record["conversion"], record["validation"]
        if (conversion["flags"] != CONVERSION_FLAGS or conversion["format"] != "MINDIR_LITE" or
                conversion["precisionScope"] != PRECISION_SCOPE or validation["scope"] != VALIDATION_SCOPE):
            raise ConversionError("provenance conversion flags/scope mismatch")
        execution_flags(conversion["execution"], "converter_lite", CONVERSION_FLAGS,
                        {"--modelFile": source_identity["file"], "--outputFile": output.stem})
        env = conversion["environment"]
        converter_root = Path(conversion["execution"]["argv"][0]).parents[3]
        libraries = [Path(p) for p in env["LD_LIBRARY_PATH"].split(":")]
        if (set(env) != {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LD_LIBRARY_PATH"} or
                env["LANG"] != "C" or env["LC_ALL"] != "C" or
                libraries[:2] != [converter_root / "tools/converter/lib", converter_root / "runtime/lib"] or
                any(not p.is_relative_to(converter_root / "runtime/third_party") for p in libraries[2:])):
            raise ConversionError("provenance loader environment differs from the isolated package recipe")
        schema = validation["schema"]
        validate_mindir_signature(schema["model"])
        if (schema["status"] != "PASS" or schema["method"] != "package-schema VerifyMetaGraphBuffer" or
                schema["helperSourceSha256"] != hashlib.sha256(SCHEMA_VERIFIER_CPP.encode()).hexdigest() or
                schema["schema"] != EXPECTED_COMPONENTS[SCHEMA] or
                json.loads(schema["execution"]["stdout"]) != schema["model"]):
            raise ConversionError("provenance schema verification mismatch")
        benchmark = validation["benchmark"]
        if (benchmark["status"] != "PASS" or benchmark["device"] != "CPU" or
                benchmark["executable"] != EXPECTED_COMPONENTS[BENCHMARK] or
                benchmark["testInput"] != synthetic_input_record()):
            raise ConversionError("provenance benchmark/test input mismatch")
        execution_flags(benchmark["execution"], "benchmark", BENCHMARK_FLAGS,
                        {"--modelFile": output.name, "--inDataFile": "synthetic-zero-fbank.f32"})
        for step in (conversion["helpProbe"], benchmark["helpProbe"], schema["compile"], schema["execution"]):
            if step["returnCode"] != 0:
                raise ConversionError("provenance records a failed tool execution")
        if "AvgRunTime" not in benchmark["execution"]["stdout"] + benchmark["execution"]["stderr"]:
            raise ConversionError("provenance lacks completed benchmark evidence")
        if (record["host"]["system"] != "Linux" or record["host"]["machine"].lower() not in ("amd64", "x86_64") or
                record["tool"] != file_identity(Path(__file__).resolve())):
            raise ConversionError("provenance host/tool identity mismatch")
    except (KeyError, IndexError, TypeError, ValueError, AttributeError, OSError) as error:
        raise ConversionError(f"invalid/incomplete provenance: {error}") from error
    return record


def convert(source: Path, package: Path, converter_root: Path | None, output: Path,
            cache: Path = DEFAULT_CACHE, cxx: str | None = None) -> dict:
    require_linux()
    check_destinations(output)
    source, output = source.absolute(), output.absolute()
    source_record = inspect_source(source)
    with prepared_package(package, converter_root, cache) as (root, package_record):
        output.parent.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix=".community-encoder-", dir=output.parent))
        try:
            env = tool_environment(root, directory)
            converter_record = converter_identity(root)
            converter_help = checked_help(root / CONVERTER, CONVERSION_FLAGS +
                                           ["--modelFile=", "--outputFile="], directory, env, "converter-help")
            benchmark_help = checked_help(root / BENCHMARK, BENCHMARK_FLAGS +
                                           ["--modelFile=", "--inDataFile="], directory, env, "benchmark-help")
            candidate = directory / output.name
            command = [str(root / CONVERTER), *CONVERSION_FLAGS, f"--modelFile={source}",
                       f"--outputFile={candidate.with_suffix('')}"]
            conversion = run_tool(command, directory, env, "conversion")
            candidate_record = file_identity(candidate)
            schema_result = schema_signature(candidate, root, directory, cxx)
            test_input = directory / "synthetic-zero-fbank.f32"
            test_input.write_bytes(bytes(998 * 80 * 4))
            if file_identity(test_input) != {k: synthetic_input_record()[k] for k in ("file", "sizeBytes", "sha256")}:
                raise ConversionError("synthetic input bytes mismatch")
            benchmark = run_tool([str(root / BENCHMARK), *BENCHMARK_FLAGS,
                                  f"--modelFile={candidate}", f"--inDataFile={test_input}"], directory, env, "benchmark")
            if "AvgRunTime" not in benchmark["stdout"] + benchmark["stderr"]:
                raise ConversionError("benchmark exit 0 did not report an inference timing result")
            if candidate_record != file_identity(candidate) or source_record != inspect_source(source):
                raise ConversionError("model/source changed during conversion or verification")
            record = {"schemaVersion": 1, "kind": "community-encoder-mindir", "status": "VERIFIED",
                      "source": source_record, "package": package_record, "converter": converter_record,
                      "conversion": {"format": "MINDIR_LITE", "flags": CONVERSION_FLAGS,
                                     "precisionScope": PRECISION_SCOPE, "environment": env,
                                     "helpProbe": converter_help, "execution": conversion},
                      "output": {**candidate_record, "format": "MINDIR_LITE", "signature": EXPECTED_SIGNATURE},
                      "validation": {"scope": VALIDATION_SCOPE, "schema": schema_result,
                                     "benchmark": {"status": "PASS", "device": "CPU",
                                                   "executable": file_identity(root / BENCHMARK),
                                                   "helpProbe": benchmark_help, "testInput": synthetic_input_record(),
                                                   "execution": benchmark}},
                      "host": {"system": platform.system(), "machine": platform.machine()},
                      "tool": file_identity(Path(__file__).resolve())}
            evidence = directory / provenance_path(output).name
            evidence.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            verify_provenance(candidate, source)
            publish_pair(candidate, evidence, output)
        except Exception as error:
            (directory / "failure.json").write_text(
                json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n", encoding="utf-8")
            raise ConversionError(f"{error}; unpublished failure artifacts retained: {directory}") from error
        shutil.rmtree(directory)
        return record


def verify_existing(source: Path, package: Path, converter_root: Path | None, output: Path,
                    cache: Path = DEFAULT_CACHE, cxx: str | None = None) -> dict:
    """No Linux binary execution; recompile only the host's header-only verifier."""
    record = verify_provenance(output, source)
    source_record = inspect_source(source)
    with prepared_package(package, converter_root, cache) as (root, package_record):
        if {k: v for k, v in record["source"].items() if k != "onnxVersion"} != {
                k: v for k, v in source_record.items() if k != "onnxVersion"}:
            raise ConversionError("provenance/source graph mismatch")
        if record["package"] != package_record or record["converter"] != converter_identity(root):
            raise ConversionError("provenance/package/converter mismatch")
        if record["validation"]["benchmark"]["executable"] != file_identity(root / BENCHMARK):
            raise ConversionError("provenance benchmark executable mismatch")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="verify-", dir=cache) as directory:
            result = schema_signature(output.absolute(), root, Path(directory).absolute(), cxx)
        previous = record["validation"]["schema"]
        for key in ("status", "method", "model", "schema", "helperSourceSha256"):
            if previous.get(key) != result[key]:
                raise ConversionError(f"provenance/actual schema verification mismatch: {key}")
    return {"status": "PASS", "output": record["output"], "provenance": file_identity(provenance_path(output)),
            "linuxBinariesExecuted": False, "scope": VALIDATION_SCOPE}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inspect", action="store_true", help="check local source/package, no Linux execution")
    mode.add_argument("--verify", action="store_true", help="audit an existing model/provenance pair, no Linux execution")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE, help="original pinned Linux x64 tar.gz; never downloaded")
    parser.add_argument("--converter-root", type=Path, help="optional unpacked root; every file is checked against --package")
    parser.add_argument("--output", type=Path, help="new .ms file; companion is .ms.provenance.json")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--cxx", help="existing host C++ compiler for header-only schema verification")
    args = parser.parse_args()
    if not args.inspect and args.output is None:
        parser.error("--output is required for conversion or --verify")
    try:
        if args.inspect:
            source = inspect_source(args.source)
            with prepared_package(args.package, args.converter_root, args.cache_dir) as (root, package):
                result = {"source": source, "package": package, "converter": converter_identity(root),
                          "plannedFlags": CONVERSION_FLAGS, "precisionScope": PRECISION_SCOPE,
                          "linuxBinariesExecuted": False,
                          "conversionAndBenchmark": "NOT_EXECUTED: flags inspected statically; Linux help/runtime probes required"}
        elif args.verify:
            result = verify_existing(args.source, args.package, args.converter_root, args.output, args.cache_dir, args.cxx)
        else:
            result = convert(args.source, args.package, args.converter_root, args.output, args.cache_dir, args.cxx)
        print(json.dumps(result, indent=2))
        return 0
    except (ConversionError, OSError) as error:
        print(f"community encoder conversion: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
