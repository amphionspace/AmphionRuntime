#!/usr/bin/env python3
"""End-to-end inference: Dingqiao TN frontend -> inference_stream.py.

Does not modify existing inference scripts. TN binaries: e2e_infer/bin/ (see install_e2e_tn.sh).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

from temp_cmu_g2p.frontend_rules import apply_frontend_rules

REPO_ROOT = Path(__file__).resolve().parent

DEFAULT_TN_BIN_DIR = REPO_ROOT / "e2e_infer" / "bin-macos-arm64"
TN_SOURCE_ROOT = REPO_ROOT / "Dingqiao_Multilingual_Text_Normalization_for_TTS"
HOST_ICU_LIB_DIR = REPO_ROOT.parent / ".venv" / "lib"
DEFAULT_RU_MORPH_MODEL = (
    REPO_ROOT
    / "Dingqiao_Multilingual_Text_Normalization_for_TTS"
    / "original"
    / "morphodita"
    / "models"
    / "russian-syntagrus-morphodita-only.tagger"
)

MODEL_TN_LANGS: dict[str, tuple[str, str]] = {
    "en-zh": ("zh", "en"),
    "en-zh-dict": ("zh", "en"),
    "ar-en": ("ar", "en"),
    "ar-en-dict": ("ar", "en"),
    "bn-en": ("bn", "en"),
    "bn-en-dict": ("bn", "en"),
    "en-ru": ("ru", "en"),
    "en-ru-dict": ("ru", "en"),
}


def _resolve_tn_langs(model_lang: str, tn_primary: str | None) -> tuple[str, str]:
    """Return (primary, secondary) TN langs, optionally overriding the model default."""
    primary, secondary = MODEL_TN_LANGS[model_lang]
    if tn_primary is None:
        return primary, secondary
    allowed = {primary, secondary}
    if tn_primary not in allowed:
        raise ValueError(
            f"--tn_primary must be one of {sorted(allowed)} for model_lang={model_lang!r}, "
            f"got {tn_primary!r}"
        )
    if tn_primary == primary:
        return primary, secondary
    return secondary, primary


def _detect_tn_primary(text: str, model_lang: str) -> str:
    """Per-line TN primary: non-English script when present, else English."""
    default_primary, secondary = MODEL_TN_LANGS[model_lang]
    pat = _SCRIPT_DETECTORS.get(default_primary)
    if pat and pat.search(text):
        return default_primary
    return secondary

_SCRIPT_DETECTORS = {
    "zh": re.compile(r"[\u4e00-\u9fff]"),
    "ar": re.compile(r"[\u0600-\u06ff\ufb50-\ufdff\ufe70-\ufefc]"),
    "bn": re.compile(r"[\u0980-\u09ff]"),
    "ru": re.compile(r"[\u0400-\u04ff]"),
    "en": re.compile(r"[A-Za-z]"),
}


def _normalize_line(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _detect_char_lang(ch: str, primary: str, secondary: str) -> str:
    for lang in (primary, secondary):
        pat = _SCRIPT_DETECTORS.get(lang)
        if pat and pat.match(ch):
            return lang
    if ch.isascii() and ch.isalpha():
        return secondary
    return "other"


def _is_chinese(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fa5"


def _is_alphabet(ch: str) -> bool:
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


# Keep plate tails with the preceding hanzi for zh_tts (ZH_PLATE_CN_* rules).
_PLATE_TAIL_AFTER_LETTER_RE = re.compile(
    r"[A-Z](?:"
    r"[0-9]{5,6}|"
    r"(?=[A-HJ-NP-Z0-9]*[A-HJ-NP-Z])[A-HJ-NP-Z0-9]{4,6}"
    r")"
)
_EN_WORD_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'._-]*(?:\s+[A-Za-z][A-Za-z0-9'._-]*)*")
_CHINESE_DIGIT_TEXT_BY_CHAR = {
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
_TECHNICAL_SYMBOL_READINGS = {
    ".": "点",
    ":": "冒号",
    "/": "斜杠",
    "\\": "反斜杠",
    "?": "问号",
    "=": "等于",
    "&": "和",
    "@": "艾特",
    "_": "下划线",
    "#": "井号",
    "+": "加",
    "-": "杠",
}
_TECHNICAL_ASCII_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z0-9./\\_@:?=&#%+\-]*[A-Za-z0-9])(?![A-Za-z0-9])"
)
_HANZI_CLOCK_MINUTE_ZERO_RE = re.compile(r"([零一二三四五六七八九十两]+)点0([1-9])分")
_SERIAL_CODE_RE = re.compile(r"((?:设备)?(?:序列号|编号)|S/N|SN)(\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\d[A-Z0-9]*)")
_VIN_CODE_RE = re.compile(r"((?:车架号\s*)?(?:VIN\s+))([A-HJ-NPR-Z0-9]{8,17})(?![A-Za-z0-9])", re.IGNORECASE)
_PRODUCT_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(vocos|Office)(\d+)(k?)(?![A-Za-z0-9])", re.IGNORECASE)


def _segment_zh_en(text: str) -> list[tuple[str, str]]:
    """Split zh-en text for TN, keeping CN plate tails on the zh_tts path.

    Plate strings such as ``沪A12345`` / ``渝A7M8N9`` must not be sent to
    ``en_tts`` (which reads digits as English). They stay attached to the
    preceding hanzi so ``zh_tts`` can apply ``ZH_PLATE_CN_*`` rules.
    """
    segments: list[tuple[str, str]] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if _is_chinese(ch):
            j = i + 1
            while j < n and _is_chinese(text[j]):
                j += 1
            plate_tail = _PLATE_TAIL_AFTER_LETTER_RE.match(text[j:])
            if plate_tail:
                j += plate_tail.end()
            elif j < n and "A" <= text[j] <= "Z" and (j + 1 >= n or _is_chinese(text[j + 1])):
                j += 1
            segments.append((text[i:j], "zh"))
            i = j
            continue

        if ch.isascii() and ch.isalpha():
            word_match = _EN_WORD_RUN_RE.match(text, i)
            if word_match:
                segments.append((word_match.group(), "en"))
                i = word_match.end()
                continue

        j = i + 1
        while j < n and not (_is_chinese(text[j]) or (text[j].isascii() and text[j].isalpha())):
            j += 1
        segments.append((text[i:j], "zh"))
        i = j

    return segments


def _segment_mixed_text(text: str, primary: str, secondary: str) -> list[tuple[str, str]]:
    if not text:
        return []

    if primary == "zh" and secondary == "en":
        return _segment_zh_en(text)

    segments: list[tuple[str, str]] = []
    buf = ""
    cur_lang = "other"
    for ch in text:
        lang = _detect_char_lang(ch, primary, secondary)
        if not buf:
            buf = ch
            cur_lang = lang
            continue
        if lang == cur_lang or lang == "other" or cur_lang == "other":
            if cur_lang == "other" and lang != "other":
                cur_lang = lang
            buf += ch
        else:
            segments.append((buf, cur_lang if cur_lang != "other" else primary))
            buf = ch
            cur_lang = lang
    if buf:
        segments.append((buf, cur_lang if cur_lang != "other" else primary))
    return segments


class DingqiaoTN:
    def __init__(self, bin_dir: Path, ru_morph_model: Path | None = None):
        self.bin_dir = bin_dir
        self.ru_morph_model = ru_morph_model
        self._procs: dict[str, subprocess.Popen] = {}

    def _bin_path(self, lang: str) -> Path:
        path = self.bin_dir / f"{lang}_tts"
        if not path.is_file():
            raise FileNotFoundError(f"TN binary not found: {path}")
        return path

    def _proc(self, lang: str) -> subprocess.Popen:
        if lang in self._procs and self._procs[lang].poll() is None:
            return self._procs[lang]

        cmd = [str(self._bin_path(lang))]
        if lang == "ru":
            if not self.ru_morph_model or not self.ru_morph_model.is_file():
                raise FileNotFoundError(
                    f"ru_tts requires --ru_morph_model (missing: {self.ru_morph_model})"
                )
            cmd.extend(["--morph-model", str(self.ru_morph_model)])

        env = os.environ.copy()
        if HOST_ICU_LIB_DIR.is_dir():
            dyld_paths = [str(HOST_ICU_LIB_DIR)]
            if env.get("DYLD_LIBRARY_PATH"):
                dyld_paths.append(env["DYLD_LIBRARY_PATH"])
            env["DYLD_LIBRARY_PATH"] = ":".join(dyld_paths)

        self._procs[lang] = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=TN_SOURCE_ROOT if TN_SOURCE_ROOT.is_dir() else None,
            env=env,
        )
        return self._procs[lang]

    def normalize_segment(self, text: str, lang: str) -> str:
        text = text.replace("\n", " ").strip()
        if not text:
            return ""
        proc = self._proc(lang)
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError(f"TN pipe unavailable for {lang}_tts")
        if proc.poll() is not None:
            raise RuntimeError(f"TN process exited ({lang}_tts, code={proc.returncode})")
        proc.stdin.write(text + "\n")
        proc.stdin.flush()
        out = proc.stdout.readline()
        return out.strip() if out else text

    def normalize_mixed(self, text: str, primary: str, secondary: str) -> str:
        if primary == "zh":
            text = _preprocess_zh_mixed_tn_input(text)
        segments = _segment_mixed_text(text, primary, secondary)
        if not segments:
            return text
        normalized = "".join(self.normalize_segment(seg, lang) for seg, lang in segments)
        if primary == "zh":
            normalized = _postprocess_zh_mixed_tn(normalized)
        return normalized

    def close(self) -> None:
        for proc in self._procs.values():
            if proc.poll() is None:
                proc.terminate()
        self._procs.clear()


def _postprocess_zh_mixed_tn(text: str) -> str:
    """Small product-side fixes for Chinese mixed TN output."""

    text = apply_frontend_rules("post_frontend", text)
    text = re.sub(r"(气温|温度|体温)负(?=[一二三四五六七八九十百千万零点两]+度)", r"\1零下", text)
    text = re.sub(r"(温度范围是)负(?=[一二三四五六七八九十百千万零点两]+到)", r"\1零下", text)
    text = re.sub(r"(\d+(?:\.\d+)?)%", lambda m: f"百分之{_number_text_to_hanzi(m.group(1))}", text)
    text = re.sub(r"\b(?:dot|point)\b", "点", text)
    text = re.sub(r"\bunderscore\b", "下划线", text)
    text = re.sub(
        r"(?<!\d)(\d+(?:\.\d+){2,})(?=[-A-Za-z])",
        lambda m: "点".join(_number_text_to_hanzi(part) for part in m.group(1).split(".")),
        text,
    )
    text = re.sub(r"(?<=\d)\.(?=\d)", "点", text)
    text = re.sub(r"(?<=[零一二三四五六七八九十百千万两])\.(?=[零一二三四五六七八九十百千万两])", "点", text)
    text = re.sub(r"(?<![A-Za-z0-9])\.(?=[A-Za-z0-9])", "点", text)
    text = re.sub(r"\^(?:2|二)", "平方", text)
    text = text.replace("=", "等于")
    text = re.sub(
        r"(?<![A-Za-z0-9])(https?|ftp)://",
        lambda m: f"{m.group(1)}冒号斜杠斜杠",
        text,
        flags=re.IGNORECASE,
    )
    text = _TECHNICAL_ASCII_TOKEN_RE.sub(_normalize_technical_ascii_token, text)
    return text


def _preprocess_zh_mixed_tn_input(text: str) -> str:
    """Preserve Chinese clock minute leading zeros before the TN binary sees them."""

    text = re.sub(r"(?<!\d)(\d{1,3}(?:,\d{3})+)\.00(?=元)", _compact_integer_currency_with_commas, text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    text = re.sub(r"(?<!\d)(\d{1,2})点0([1-9])分", r"\1点零\2分", text)
    text = _HANZI_CLOCK_MINUTE_ZERO_RE.sub(lambda match: f"{match.group(1)}点零{_CHINESE_DIGIT_TEXT_BY_CHAR[match.group(2)]}分", text)
    text = re.sub(r"(?<!\d)(\d+)小时0([1-9])分钟", r"\1小时零\2分钟", text)
    text = re.sub(r"(\d{2,4}年)0([1-9])月", r"\1零\2月", text)
    text = re.sub(r"(月)0([1-9])日", r"\1零\2日", text)
    text = apply_frontend_rules("pre_tn", text)
    text = _VIN_CODE_RE.sub(lambda match: match.group(1) + _normalize_serial_code(match.group(2)), text)
    text = _PRODUCT_CODE_RE.sub(lambda match: match.group(1) + _normalize_serial_code(match.group(2)) + match.group(3), text)
    text = _SERIAL_CODE_RE.sub(lambda match: match.group(1) + match.group(2) + _normalize_serial_code(match.group(3)), text)
    return text


def _normalize_serial_code(code: str) -> str:
    return "".join(_CHINESE_DIGIT_TEXT_BY_CHAR.get(ch, ch) for ch in code)


def _normalize_technical_ascii_token(match: re.Match[str]) -> str:
    token = match.group(1)
    if _looks_like_ipv6(token) or not any(ch in _TECHNICAL_SYMBOL_READINGS for ch in token):
        return token
    return "".join(_TECHNICAL_SYMBOL_READINGS.get(ch, ch) for ch in token)


def _looks_like_ipv6(token: str) -> bool:
    return token.count(":") >= 2 and all(ch.isdigit() or ch.lower() in "abcdef" or ch == ":" for ch in token)


def _number_text_to_hanzi(text: str) -> str:
    integer, dot, fraction = text.partition(".")
    result = _integer_text_to_hanzi(integer)
    if not dot:
        return result
    return result + "点" + "".join(_CHINESE_DIGIT_TEXT_BY_CHAR[ch] for ch in fraction)


def _integer_text_to_hanzi(text: str) -> str:
    try:
        value = int(text)
    except ValueError:
        return "".join(_CHINESE_DIGIT_TEXT_BY_CHAR.get(ch, ch) for ch in text)
    if value == 0:
        return "零"
    if value < 10:
        return _CHINESE_DIGIT_TEXT_BY_CHAR[str(value)]
    if value < 20:
        ones = value % 10
        return "十" + ("" if ones == 0 else _CHINESE_DIGIT_TEXT_BY_CHAR[str(ones)])
    if value < 100:
        tens, ones = divmod(value, 10)
        return _CHINESE_DIGIT_TEXT_BY_CHAR[str(tens)] + "十" + (
            "" if ones == 0 else _CHINESE_DIGIT_TEXT_BY_CHAR[str(ones)]
        )
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        if remainder == 0:
            suffix = ""
        elif remainder < 10:
            suffix = "零" + _CHINESE_DIGIT_TEXT_BY_CHAR[str(remainder)]
        else:
            suffix = _integer_text_to_hanzi(str(remainder))
        return _CHINESE_DIGIT_TEXT_BY_CHAR[str(hundreds)] + "百" + suffix
    return "".join(_CHINESE_DIGIT_TEXT_BY_CHAR.get(ch, ch) for ch in text)


def _compact_integer_currency_with_commas(match: re.Match[str]) -> str:
    value = int(match.group(1).replace(",", ""))
    if value >= 100_000_000 and value % 100_000_000 == 0:
        return f"{value // 100_000_000}亿"
    if value >= 10_000 and value % 10_000 == 0:
        return f"{value // 10_000}万"
    return str(value)


def _parse_input_line(line: str):
    parts = [p.strip() for p in line.strip().split("|")]
    if not parts or not parts[0]:
        return None
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    raise ValueError(f"Invalid input line (expected text or wav|text): {line!r}")


def _format_manifest_line(wav_path: str, text: str, spk_id: str | None) -> str:
    if spk_id is None:
        return f"{wav_path}|{text}"
    return f"{wav_path}|{spk_id}|{text}"


def rewrite_manifest_with_spk(
    input_path: Path,
    output_path: Path,
    spk_id: int,
) -> int:
    """Rewrite manifest so every line uses the same ``wav|spk_id|text`` format."""
    rows: list[str] = []
    for raw_line in input_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        wav_path, _, text = _parse_input_line(line)
        if wav_path is None:
            continue
        rows.append(_format_manifest_line(wav_path, text, str(spk_id)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return len(rows)


def build_tn_manifest(
    input_path: Path,
    output_path: Path,
    *,
    model_lang: str,
    tn: DingqiaoTN,
    utterance_prefix: str,
    limit: int,
    tn_primary: str | None = None,
    force_spk_id: int | None = None,
) -> dict:
    lines = input_path.read_text(encoding="utf-8").splitlines()
    if limit > 0:
        lines = lines[:limit]

    out_rows: list[str] = []
    stats: dict = {"input_lines": 0, "written": 0, "raw_only": 0, "tn_primary_counts": {}}

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        stats["input_lines"] += 1

        parsed = _parse_input_line(line)
        if parsed is None:
            continue
        wav_path, spk_id, text = parsed
        text = _normalize_line(text)
        if wav_path is None:
            stats["raw_only"] += 1
            wav_path = f"{utterance_prefix}-{idx:03d}.wav"

        line_primary = tn_primary if tn_primary is not None else _detect_tn_primary(text, model_lang)
        primary, secondary = _resolve_tn_langs(model_lang, line_primary)
        stats["tn_primary_counts"][primary] = stats["tn_primary_counts"].get(primary, 0) + 1

        tn_text = tn.normalize_mixed(text, primary, secondary)
        out_spk_id = str(force_spk_id) if force_spk_id is not None else spk_id
        out_rows.append(_format_manifest_line(wav_path, tn_text, out_spk_id))
        stats["written"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(out_rows) + ("\n" if out_rows else ""), encoding="utf-8")
    return stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="E2E TTS inference: Dingqiao TN -> inference_stream.py",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--model_lang", required=True, choices=sorted(MODEL_TN_LANGS))
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--input_txt", required=True, help="Raw text (one line each) or manifest wav|text")
    p.add_argument("--output_dir", required=True)
    p.add_argument("--output_txt", required=True)
    p.add_argument("--tn_bin_dir", type=Path, default=DEFAULT_TN_BIN_DIR)
    p.add_argument("--ru_morph_model", type=Path, default=DEFAULT_RU_MORPH_MODEL)
    p.add_argument("--utterance_prefix", default=None, help="Prefix for auto wav ids (default: model primary lang)")
    p.add_argument(
        "--tn_primary",
        default=None,
        help="Force TN primary lang for all lines (default: auto-detect per line from script)",
    )
    p.add_argument("--limit", type=int, default=0, help="Only process first N non-empty lines (0=all)")
    p.add_argument(
        "--spk_id",
        type=int,
        default=None,
        help="Force the same speaker id for every utterance (written as wav|spk_id|text)",
    )
    p.add_argument("--skip_tn", action="store_true", help="Input is already TN-normalized manifest")
    p.add_argument("--keep_manifest", action="store_true", help="Keep generated TN manifest under output_dir")
    p.add_argument("--inference_script", type=Path, default=REPO_ROOT / "inference_stream.py")

    # Common inference_stream args (forwarded as-is)
    p.add_argument("--vocos_checkpoint", default=str(REPO_ROOT / "vocos" / "generator.ckpt"))
    p.add_argument("--vocos_root", default=str(REPO_ROOT))
    p.add_argument("--output_sample_rate", type=int, default=24000)
    p.add_argument("--n_timesteps", type=int, default=10)
    p.add_argument("--length_scale", type=float, default=1.0)
    p.add_argument("--temperature", type=float, default=0.667)
    p.add_argument("--chunk_size", type=int, default=50)
    p.add_argument("--mel_cache_len", type=int, default=8)
    p.add_argument("--pre_lookahead_len", type=int, default=3)
    p.add_argument("--num_decoding_left_chunks", type=int, default=-1)
    p.add_argument("--add_blank", action="store_true", default=False)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_txt)
    output_dir = Path(args.output_dir)
    output_txt = Path(args.output_txt)

    if not input_path.is_file():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 1
    if not args.inference_script.is_file():
        print(f"Inference script not found: {args.inference_script}", file=sys.stderr)
        return 1

    primary_lang = MODEL_TN_LANGS[args.model_lang][0]
    utterance_prefix = args.utterance_prefix or primary_lang

    if args.skip_tn:
        manifest_path = input_path
        print(f"[e2e] SKIP_TN: using manifest as-is: {manifest_path}")
        if args.spk_id is not None:
            manifest_path = output_dir / "tn_manifest.txt"
            written = rewrite_manifest_with_spk(input_path, manifest_path, args.spk_id)
            if written == 0:
                print("[e2e] ERROR: no lines written after applying --spk_id", file=sys.stderr)
                return 2
            print(
                f"[e2e] Applied --spk_id={args.spk_id} to all lines: "
                f"{input_path} -> {manifest_path} (written={written})"
            )
    else:
        if not args.tn_bin_dir.is_dir():
            print(
                f"TN bin dir not found: {args.tn_bin_dir}\n"
                "Build Dingqiao TN binaries or pass --tn_bin_dir.",
                file=sys.stderr,
            )
            return 1

        manifest_path = output_dir / "tn_manifest.txt"
        if args.tn_primary is not None:
            try:
                _resolve_tn_langs(args.model_lang, args.tn_primary)
            except ValueError as exc:
                print(f"[e2e] ERROR: {exc}", file=sys.stderr)
                return 1
        tn = DingqiaoTN(args.tn_bin_dir, ru_morph_model=args.ru_morph_model)
        try:
            stats = build_tn_manifest(
                input_path,
                manifest_path,
                model_lang=args.model_lang,
                tn=tn,
                utterance_prefix=utterance_prefix,
                limit=args.limit,
                tn_primary=args.tn_primary,
                force_spk_id=args.spk_id,
            )
        finally:
            tn.close()

        if stats["written"] == 0:
            print("[e2e] ERROR: no lines written after TN", file=sys.stderr)
            return 2

        tn_counts = stats.get("tn_primary_counts") or {}
        tn_summary = (
            f"tn_primary={args.tn_primary}"
            if args.tn_primary is not None
            else "tn_primary=auto(" + ",".join(f"{k}={v}" for k, v in sorted(tn_counts.items())) + ")"
        )
        print(
            f"[e2e] TN done: {input_path} -> {manifest_path} "
            f"(written={stats['written']} raw_only={stats['raw_only']} {tn_summary}"
            f"{f' spk_id={args.spk_id}' if args.spk_id is not None else ''})"
        )
        if args.keep_manifest:
            normalized_copy = output_dir / "normalized.txt"
            normalized_copy.write_text(
                "\n".join(row.split("|", 1)[-1] for row in manifest_path.read_text(encoding="utf-8").splitlines() if row)
                + "\n",
                encoding="utf-8",
            )

    cmd = [
        sys.executable,
        str(args.inference_script),
        "--model_lang",
        args.model_lang,
        "--checkpoint",
        args.checkpoint,
        "--input_txt",
        str(manifest_path),
        "--output_dir",
        str(output_dir),
        "--output_txt",
        str(output_txt),
        "--vocos_checkpoint",
        args.vocos_checkpoint,
        "--vocos_root",
        args.vocos_root,
        "--output_sample_rate",
        str(args.output_sample_rate),
        "--n_timesteps",
        str(args.n_timesteps),
        "--length_scale",
        str(args.length_scale),
        "--temperature",
        str(args.temperature),
        "--chunk_size",
        str(args.chunk_size),
        "--mel_cache_len",
        str(args.mel_cache_len),
        "--pre_lookahead_len",
        str(args.pre_lookahead_len),
        "--num_decoding_left_chunks",
        str(args.num_decoding_left_chunks),
    ]
    if args.add_blank:
        cmd.append("--add_blank")

    print(f"[e2e] Running: {' '.join(cmd)}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
