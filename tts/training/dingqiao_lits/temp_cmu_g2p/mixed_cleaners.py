"""Cleaner hook for LITs inference: Chinese hanzi lexicon + English CMUdict G2P."""

from __future__ import annotations

import sys
from pathlib import Path
import re

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from english_frontend import preprocess_english_input  # noqa: E402
from frontend_rules import apply_frontend_rules  # noqa: E402

_ASCII_ALNUM_RUN_RE = re.compile(r"[A-Za-z0-9]+")
_HANZI_BEFORE_ARPA_RE = re.compile(r"([\u4e00-\u9fff])(?=[A-Z])")
_ARPA_BEFORE_HANZI_RE = re.compile(r"([A-Z]{1,3}[012]?)(?=[\u4e00-\u9fff])")
_PERCENT_NUMBER_RE = re.compile(r"(\d{1,3})%")
_DOT_BETWEEN_DIGITS_RE = re.compile(r"(?<=\d)\.(?=\d)")
_DOT_BETWEEN_HANZI_NUMERALS_RE = re.compile(r"(?<=[零一二三四五六七八九十百千万两])\.(?=[零一二三四五六七八九十百千万两])")
_LEADING_DOT_ASCII_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])\.(?=[A-Za-z0-9])")
_URL_SCHEME_SEP_RE = re.compile(r"(?<=[A-Za-z])://")
_URL_SCHEME_PREPROCESSED_RE = re.compile(r"(?<![A-Za-z0-9])(https?|ftp):\s*/\s*", re.IGNORECASE)
_CARET_POWER_TWO_RE = re.compile(r"\^(?:2|二)")
_TECH_ASCII_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9][A-Za-z0-9._@:/?=&#%+\\-\\\\]*[A-Za-z0-9])(?![A-Za-z0-9])")
_TECH_SYMBOL_READINGS = {
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
_DIGIT_TO_HANZI = {
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
_LETTER_TO_ARPA = {
    "A": "EY1",
    "B": "B IY1",
    "C": "S IY1",
    "D": "D IY1",
    "E": "IY1",
    "F": "EH1 F",
    "G": "JH IY1",
    "H": "EY1 CH",
    "I": "AY1",
    "J": "JH EY1",
    "K": "K EY1",
    "L": "EH1 L",
    "M": "EH1 M",
    "N": "EH1 N",
    "O": "OW1",
    "P": "P IY1",
    "Q": "K Y UW1",
    "R": "AA1 R",
    "S": "EH1 S",
    "T": "T IY1",
    "U": "Y UW1",
    "V": "V IY1",
    "W": "D AH1 B AH0 L Y UW0",
    "X": "EH1 K S",
    "Y": "W AY1",
    "Z": "Z IY1",
}
_ACRONYM_WORD_READINGS = frozenset({"SIM"})


def _integer_to_hanzi(value: str) -> str:
    """Convert short percent integers to natural Chinese, e.g. 58 -> 五十八."""
    value = value.lstrip("0") or "0"
    if not value.isdigit() or len(value) > 3:
        return "".join(_DIGIT_TO_HANZI[ch] for ch in value if ch in _DIGIT_TO_HANZI)
    number = int(value)
    if number < 10:
        return _DIGIT_TO_HANZI[str(number)]
    if number < 20:
        return "十" + (_DIGIT_TO_HANZI[str(number % 10)] if number % 10 else "")
    if number < 100:
        tens, ones = divmod(number, 10)
        return _DIGIT_TO_HANZI[str(tens)] + "十" + (_DIGIT_TO_HANZI[str(ones)] if ones else "")
    hundreds, rest = divmod(number, 100)
    if rest == 0:
        return _DIGIT_TO_HANZI[str(hundreds)] + "百"
    if rest < 10:
        return _DIGIT_TO_HANZI[str(hundreds)] + "百零" + _DIGIT_TO_HANZI[str(rest)]
    return _DIGIT_TO_HANZI[str(hundreds)] + "百" + _integer_to_hanzi(str(rest))


def _normalize_numeric_symbols(text: str) -> str:
    text = _PERCENT_NUMBER_RE.sub(lambda match: "百分之" + _integer_to_hanzi(match.group(1)), text)
    text = _DOT_BETWEEN_DIGITS_RE.sub("点", text)
    text = _DOT_BETWEEN_HANZI_NUMERALS_RE.sub("点", text)
    return _LEADING_DOT_ASCII_TOKEN_RE.sub("点", text)


def _looks_like_ipv6(token: str) -> bool:
    return token.count(":") >= 2 and all(ch in "0123456789abcdefABCDEF:" for ch in token)


def _normalize_technical_symbols(text: str) -> str:
    """Read symbols inside URL/email/path/package/version-like ASCII tokens."""

    text = _CARET_POWER_TWO_RE.sub("平方", text)
    text = text.replace("=", "等于")
    text = _URL_SCHEME_SEP_RE.sub("冒号斜杠斜杠", text)
    text = _URL_SCHEME_PREPROCESSED_RE.sub(lambda match: match.group(1) + "冒号斜杠斜杠", text)

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        if _looks_like_ipv6(token):
            return token
        if not any(symbol in token for symbol in _TECH_SYMBOL_READINGS):
            return token
        return "".join(_TECH_SYMBOL_READINGS.get(ch, ch) for ch in token)

    return _TECH_ASCII_TOKEN_RE.sub(repl, text)


def _expand_plate_alnum_runs(text: str) -> str:
    """Read plate-like ASCII runs character by character.

    Chinese police/vehicle queries often contain strings such as ``冀R65438``.
    The generic mixed frontend treats digits as unsupported English input and
    can drop them, so only plate-like alnum runs are expanded here.
    """

    def repl(match: re.Match[str]) -> str:
        token = match.group()
        lower_word_prefix = re.match(r"([a-z]{2,})(\d+)$", token)
        if lower_word_prefix:
            word, digits = lower_word_prefix.groups()
            digit_text = " ".join(_DIGIT_TO_HANZI[ch] for ch in digits)
            return f" {word} {digit_text} "

        should_expand = any(ch.isdigit() for ch in token) or (
            token.isalpha() and token.isupper()
        )
        if token.upper() in _ACRONYM_WORD_READINGS:
            return f" {token} "
        if not should_expand:
            return f" {token} "

        pieces: list[str] = []
        for ch in token:
            if ch.isdigit():
                pieces.append(_DIGIT_TO_HANZI[ch])
            elif ch.isalpha():
                pieces.append(ch.upper())
            else:
                pieces.append(ch)
        return " " + " ".join(pieces) + " "

    return _ASCII_ALNUM_RUN_RE.sub(repl, text)


def en_zh_dict_mixed_cleaners(text: str) -> str:
    """Hybrid cleaner: hanzi -> lexicon pinyin; English text -> CMUdict ARPAbet.

    Plate numbers, digit-by-digit reads, and similar spoken-form rules are handled
    by the Dingqiao TN frontend (``zh_tts`` / ``ZH_PLATE_*`` rules). This cleaner
    only performs script-aware English G2P and Chinese Bopomofo conversion.
    """
    if not text:
        return ""

    from english_frontend import is_arpabet_input
    from lits.text.language_cleaners import (
        english_direct_phoneme_cleaners,
        _hanzi_char_re,
        _hanzi_to_bopomofo_tokens,
        _pinyin_to_bopomofo_tokens,
    )

    if is_arpabet_input(text):
        return english_direct_phoneme_cleaners(text)

    text = apply_frontend_rules("pre_frontend", text)
    text = apply_frontend_rules("post_frontend", text)
    text = _normalize_numeric_symbols(text)
    text = _normalize_technical_symbols(text)
    text = _expand_plate_alnum_runs(text)
    arpa_line = preprocess_english_input(text)
    arpa_line = _HANZI_BEFORE_ARPA_RE.sub(r"\1 ", arpa_line)
    arpa_line = _ARPA_BEFORE_HANZI_RE.sub(r"\1 ", arpa_line)
    if _hanzi_char_re.search(arpa_line):
        return _hanzi_to_bopomofo_tokens(arpa_line)
    return _pinyin_to_bopomofo_tokens(arpa_line)


def ar_en_dict_mixed_cleaners(text: str) -> str:
    """Hybrid cleaner: Arabic chars (space-separated) + English CMUdict G2P + ARPAbet pass-through.

    TN should run before G2P for numbers, currency, and abbreviations. This cleaner
    converts English words to ARPAbet via CMUdict, normalizes slash boundaries to
    ``_``, then expands Arabic script into per-character tokens (same as training).
    """
    if not text:
        return ""

    from lits.text.language_cleaners import (
        ar_en_mixed_cleaners,
        english_direct_phoneme_cleaners,
    )

    arpa_line = preprocess_english_input(text)
    arpa_line = english_direct_phoneme_cleaners(arpa_line)
    return ar_en_mixed_cleaners(arpa_line)
