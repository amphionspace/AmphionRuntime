#!/usr/bin/env python3
"""Generate host-TN frontend golden rows and run Android JVM parity tests."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable


MODEL_ID = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
MODEL_VERSION = "0.1.0"
CHINESE_DIGITS = {
    "0": "零",
    "1": "一",
    "2": "二",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}
PLATE_PROVINCES = set("京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼")
HANZI_CLOCK_MINUTE_ZERO_RE = re.compile(r"([零一二三四五六七八九十两]+)点0([1-9])分")
CONNECTOR_HYPHEN_RE = re.compile(r"(?<![A-Za-z0-9])(USB|Type)-([A-Za-z])(?![A-Za-z0-9])", re.I)
SERIAL_CODE_RE = re.compile(r"((?:设备)?(?:序列号|编号)|S/N|SN)(\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\d[A-Z0-9]*)")
PERCENTILE_CODE_RE = re.compile(r"P\d{1,3}")


class TnProcess:
    def __init__(self, binary: Path, working_dir: Path):
        if not binary.is_file():
            raise FileNotFoundError(f"missing host TN binary: {binary}")
        env = os.environ.copy()
        env["TTS_RULES_ROOT"] = str(working_dir)
        env["TTS_RULES_FORMAT"] = "v2"
        self.process = subprocess.Popen(
            [str(binary)],
            cwd=str(working_dir),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def normalize(self, text: str) -> str:
        if not text:
            return text
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("TN process pipes were not opened")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = ""
            if self.process.stderr is not None:
                stderr = self.process.stderr.read()
            raise RuntimeError(f"TN process exited without output: {stderr}")
        normalized = line.strip()
        return normalized or text

    def close(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.terminate()
            self.process.wait(timeout=1)
        except Exception:
            self.process.kill()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_model_root() -> Path:
    return (
        repo_root()
        / "tts"
        / "tools"
        / "trial-export"
        / MODEL_ID
        / MODEL_VERSION
    )


def load_cases(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def prepare_input_for_tn(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = HANZI_CLOCK_MINUTE_ZERO_RE.sub(lambda m: f"{m.group(1)}点零{CHINESE_DIGITS[m.group(2)]}分", text)
    text = CONNECTOR_HYPHEN_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", text)
    text = SERIAL_CODE_RE.sub(lambda m: m.group(1) + m.group(2) + "".join(CHINESE_DIGITS.get(ch, ch) for ch in m.group(3)), text)
    return text


def is_ascii_letter(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def scan_ascii_run(text: str, start: int) -> int:
    index = start
    while index < len(text):
        ch = text[index]
        if not (is_ascii_letter(ch) or ch.isdigit() or ch in {"'", ".", "_", "-"}):
            break
        index += 1
    return index


def scan_non_ascii_run(text: str, start: int) -> int:
    index = start
    while index < len(text):
        ch = text[index]
        is_celsius_unit = index > 0 and text[index - 1] == "°" and ch in {"C", "c"}
        if is_ascii_letter(ch) and not is_celsius_unit:
            break
        index += 1
    return index


def protected_ascii_run_lang(text: str, start: int, end: int, run: str) -> str | None:
    if run in {"SO2", "CO2", "C6H12O6"}:
        return "en"
    touches_chinese = (start > 0 and is_cjk(text[start - 1])) or (end < len(text) and is_cjk(text[end]))
    if not touches_chinese:
        return None
    has_digit = any(ch.isdigit() for ch in run)
    upper_count = sum(1 for ch in run if "A" <= ch <= "Z")
    has_lower = any("a" <= ch <= "z" for ch in run)
    follows_plate_province = start > 0 and text[start - 1] in PLATE_PROVINCES
    is_percentile_code = PERCENTILE_CODE_RE.fullmatch(run) is not None
    if has_digit and not has_lower and (upper_count >= 1 or follows_plate_province or is_percentile_code):
        return "zh"
    return None


def segment_zh_en(text: str) -> Iterable[tuple[str, str]]:
    index = 0
    while index < len(text):
        if is_ascii_letter(text[index]):
            end = scan_ascii_run(text, index)
            segment = text[index:end]
            yield segment, protected_ascii_run_lang(text, index, end, segment) or "en"
            index = end
        else:
            end = scan_non_ascii_run(text, index)
            yield text[index:end], "zh"
            index = end


def normalize_with_host_tn(row: dict, zh_tn: TnProcess, en_tn: TnProcess) -> str:
    raw_text = prepare_input_for_tn(row["raw_text"])
    language = row.get("language", "zh-en")
    language_context = row.get("language_context", language)
    if language == "en-US" or language_context == "en-US":
        return en_tn.normalize(raw_text)
    parts = []
    for segment, lang in segment_zh_en(raw_text):
        normalized = en_tn.normalize(segment) if lang == "en" else zh_tn.normalize(segment)
        if segment.startswith(" ") and not normalized.startswith(" "):
            normalized = " " + normalized
        if segment.endswith(" ") and not normalized.endswith(" "):
            normalized += " "
        parts.append(normalized)
    return "".join(parts)


def python_cleaned_text(repo: Path, tn_text: str, language: str) -> str:
    dingqiao_root = repo / "dingqiao_lits"
    sys.path.insert(0, str(dingqiao_root))
    from lits.text import text_to_sequence  # pylint: disable=import-error,import-outside-toplevel

    cleaner = "english_direct_phoneme_cleaners" if language == "en-US" else "en_zh_dict_mixed_cleaners"
    _, cleaned = text_to_sequence(tn_text, [cleaner])
    return cleaned


def generate_golden(args: argparse.Namespace) -> Path:
    root = repo_root()
    model_root = Path(args.model_root or default_model_root())
    zh_tn = TnProcess(Path(args.zh_tn), model_root)
    en_tn = TnProcess(Path(args.en_tn), model_root)
    output = Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix="android-frontend-parity-")) / "golden.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("w", encoding="utf-8") as handle:
            for row in load_cases(Path(args.cases)):
                tn_text = row.get("tn_text") or normalize_with_host_tn(row, zh_tn, en_tn)
                cleaned_text = row.get("cleaned_text") or python_cleaned_text(root, tn_text, row.get("language", "zh-en"))
                out = dict(row)
                out["tn_text"] = tn_text
                out["cleaned_text"] = cleaned_text
                handle.write(json.dumps(out, ensure_ascii=False) + "\n")
    finally:
        zh_tn.close()
        en_tn.close()
    return output


def run_gradle(golden: Path) -> None:
    android_root = repo_root() / "tts" / "android"
    command = [
        "./gradlew",
        ":sdk:testDebugUnitTest",
        "--tests",
        "com.lits.tts.sdk.internal.AndroidFrontendGoldenParityTest",
        f"-Dandroid.frontend.golden={golden}",
    ]
    subprocess.run(command, cwd=android_root, check=True)


def main() -> None:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases",
        default=str(root / "tools" / "dingqiao-android" / "frontend_golden_cases.jsonl"),
    )
    parser.add_argument("--model-root", default=str(default_model_root()))
    parser.add_argument("--zh-tn", required=True, help="macOS/Linux host zh_tts binary")
    parser.add_argument("--en-tn", required=True, help="macOS/Linux host en_tts binary")
    parser.add_argument("--output", default="")
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()

    golden = generate_golden(args)
    print(f"generated Android frontend parity golden: {golden}")
    if not args.generate_only:
        run_gradle(golden)


if __name__ == "__main__":
    main()
