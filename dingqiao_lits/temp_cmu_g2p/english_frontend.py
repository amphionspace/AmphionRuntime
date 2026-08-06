"""English CMUdict frontend with ARPAbet pass-through.

Two input modes (auto-detected):
  1. ARPAbet phoneme sequence  -> normalize separators, keep phonemes as-is
  2. English plain text         -> CMUdict lookup, slash-delimited output

Output example:
  CHAP -> CH AE1 P / .
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from arpa_tokens import (  # noqa: E402
    ARPA_BOUNDARY_TOKENS,
    ARPA_PUNCT_TOKENS,
    ARPA_TOKENS,
    SENTENCE_END_PUNCT,
)
from cmudict_loader import DEFAULT_CMUDICT_PATH  # noqa: E402
from g2p_engine import CMUDictG2P, DEFAULT_SUPPLEMENT_PATH, tokenize_english_text  # noqa: E402

_ENGLISH_WORD_TOKEN_RE = re.compile(r"^[A-Za-z]+(?:[''-][A-Za-z]+)*$")
_NON_ENGLISH_SCRIPT_RE = re.compile(
    r"[\u4e00-\u9fff\u0600-\u06ff\u0980-\u09ff\u0400-\u04ff\u0300-\u0301]"
)
_BOUNDARY_TOKENS = frozenset({"_", "/", "|"})
_DEFAULT_G2P: CMUDictG2P | None = None


def _mixed_language_helpers():
    from lits.text.language_cleaners import (
        _is_punctuation_token,
        _pinyin_syllable_re,
    )

    return _pinyin_syllable_re, _is_punctuation_token


def _tokenize_latin_for_dict_g2p(segment: str) -> list[str]:
    """Space-delimited tokens: each is pinyin, ARPAbet, boundary, punct, or English word."""
    from lits.text.language_cleaners import (
        _is_zh_punct_char,
        _normalize_zh_punct_to_halfwidth,
    )

    text = _normalize_zh_punct_to_halfwidth(segment)
    tokens: list[str] = []
    for raw in text.split():
        if not raw:
            continue
        if raw in _BOUNDARY_TOKENS:
            tokens.append(raw)
            continue
        for piece in _detach_trailing_punct(raw):
            if _is_zh_punct_char(piece) or _is_punct_token(piece):
                tokens.append(piece)
            else:
                tokens.append(piece)
    return tokens


def _is_pinyin_token(token: str) -> bool:
    return bool(_mixed_language_helpers()[0].match(token))


def _is_punct_token(token: str) -> bool:
    return _mixed_language_helpers()[1](token)


def _is_arpabet_like_token(token: str) -> bool:
    """Whole space-token is one ARPAbet symbol (EY1, CH, L); ``Good`` / ``GOOD`` are not."""
    if _is_pinyin_token(token):
        return False
    if any(ch.islower() for ch in token):
        return False
    return is_arpa_phoneme(token)


def _is_english_word_token(token: str) -> bool:
    """TN 后的英文词：纯字母，无拼音声调数字（如 ni3），非 ARPAbet 音素。"""
    if not _ENGLISH_WORD_TOKEN_RE.match(token):
        return False
    if _is_pinyin_token(token):
        return False
    if _is_arpabet_like_token(token):
        return False
    return True


def _is_isolated_letter_token(token: str) -> bool:
    """Single A–Z letter in mixed zh-en text (e.g. plate ``M``), not an ARPAbet unit."""
    return len(token) == 1 and token.isalpha()


def _latin_token_needs_g2p(token: str) -> bool:
    if token in _BOUNDARY_TOKENS or _is_punct_token(token):
        return False
    if _is_isolated_letter_token(token):
        return True
    return _is_english_word_token(token)


def _append_slash_arpa_chunk(parts: list[str], phones: list[str]) -> None:
    chunk = " ".join(phones)
    if parts and not parts[-1].endswith(" "):
        parts.append(" ")
    parts.append(f"/ {chunk} /")
    parts.append(" ")


def get_default_g2p() -> CMUDictG2P:
    global _DEFAULT_G2P
    if _DEFAULT_G2P is None:
        _DEFAULT_G2P = CMUDictG2P.from_paths()
    return _DEFAULT_G2P


def is_arpa_phoneme(token: str) -> bool:
    return token in ARPA_TOKENS


def is_arpa_token(token: str) -> bool:
    if token in ARPA_BOUNDARY_TOKENS or token in ARPA_PUNCT_TOKENS:
        return True
    return is_arpa_phoneme(token)


_PUNCT_FOR_DETACH = sorted(ARPA_PUNCT_TOKENS | SENTENCE_END_PUNCT, key=len, reverse=True)


def _detach_trailing_punct(token: str) -> list[str]:
    """Split punctuation glued to token edges, e.g. ``P.``, ``carbon;.``, ``\"cobham,\"``."""
    if is_arpa_token(token) or token in ARPA_BOUNDARY_TOKENS:
        return [token]
    if not token:
        return []

    parts: list[str] = []
    while token:
        stripped = False
        for punct in _PUNCT_FOR_DETACH:
            if token.startswith(punct):
                parts.append(punct)
                token = token[len(punct) :]
                stripped = True
                break
        if stripped:
            continue

        trailing: list[str] = []
        while token:
            found = False
            for punct in _PUNCT_FOR_DETACH:
                if len(token) > len(punct) and token.endswith(punct):
                    trailing.insert(0, punct)
                    token = token[: -len(punct)]
                    found = True
                    break
            if not found:
                break

        if token:
            parts.append(token)
        parts.extend(trailing)
        break
    return parts


def _is_punct_unit(unit: str) -> bool:
    return unit in SENTENCE_END_PUNCT or unit in ARPA_PUNCT_TOKENS or _is_punct_token(unit)


def parse_arpa_word_units(text: str) -> list[str]:
    """Split ARPAbet text into word-level units (``HH AH0 L OW1``, ``.``, etc.)."""
    units: list[str] = []
    for chunk in re.split(r"\s*/\s*", text.strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        phoneme_buf: list[str] = []
        for token in chunk.split():
            for piece in _detach_trailing_punct(token):
                if is_arpa_phoneme(piece):
                    phoneme_buf.append(piece)
                else:
                    if phoneme_buf:
                        units.append(" ".join(phoneme_buf))
                        phoneme_buf = []
                    units.append(piece)
        if phoneme_buf:
            units.append(" ".join(phoneme_buf))
    return units


def _flatten_arpa_word_units(units: list[str]) -> list[str]:
    """Expand word units to atomic phoneme/punct tokens for validation."""
    flat: list[str] = []
    for unit in units:
        for token in unit.split():
            flat.extend(_detach_trailing_punct(token))
    return flat


def has_raw_english_words(text: str) -> bool:
    if _NON_ENGLISH_SCRIPT_RE.search(text):
        for segment, is_latin in _iter_mixed_script_segments(text):
            if is_latin and _latin_run_has_english_words(segment):
                return True
        return False
    return _latin_run_has_english_words(text)


def _latin_run_has_english_words(segment: str) -> bool:
    for token in _tokenize_latin_for_dict_g2p(segment):
        if token in _BOUNDARY_TOKENS or _is_punct_token(token):
            continue
        if _latin_token_needs_g2p(token):
            return True
    return False


def is_arpabet_input(text: str) -> bool:
    """Return True when input is already an ARPAbet phoneme sequence."""
    stripped = text.strip()
    if not stripped:
        return False

    units = parse_arpa_word_units(stripped)
    if not units:
        return False

    for token in _flatten_arpa_word_units(units):
        if any(ch.islower() for ch in token):
            return False
        if not is_arpa_token(token):
            return False
    return True


def _ensure_sentence_end(units: list[str]) -> list[str]:
    if not units:
        return units
    if _is_punct_unit(units[-1]):
        return units
    return [*units, "."]


def format_word_units(units: list[str]) -> str:
    """Join word units with `` / ``; phonemes inside each unit stay space-separated."""
    return " / ".join(units)


def normalize_arpabet_input(text: str, *, add_sentence_end: bool = True) -> str:
    """Normalize pre-computed ARPAbet to word-level ``phoneme phoneme / word / .`` format."""
    units = parse_arpa_word_units(text)
    if add_sentence_end:
        units = _ensure_sentence_end(units)
    return format_word_units(units)


def english_text_to_slash_arpa(
    text: str,
    g2p: CMUDictG2P,
    *,
    add_sentence_end: bool = True,
) -> str:
    """Convert English plain text to word-level ARPAbet (``CH AE1 P / .``)."""
    tokens = tokenize_english_text(text)
    units: list[str] = []
    for idx, (kind, surface) in enumerate(tokens):
        if kind == "punct":
            if surface == "-":
                prev_word = idx > 0 and tokens[idx - 1][0] == "word"
                next_word = idx + 1 < len(tokens) and tokens[idx + 1][0] == "word"
                if prev_word and next_word:
                    continue
            units.append(surface)
            continue

        phones = _lookup_english_token_phonemes(
            g2p,
            surface,
            prefer_letter_name=_prefer_letter_name_in_english(surface, idx, tokens),
        )
        if phones:
            units.append(" ".join(phones))

    if add_sentence_end:
        units = _ensure_sentence_end(units)
    return format_word_units(units)


def _iter_mixed_script_segments(text: str):
    """Yield (segment, is_latin_run) pairs, splitting CJK from Latin/punct runs."""
    i = 0
    n = len(text)
    while i < n:
        if _NON_ENGLISH_SCRIPT_RE.match(text[i]):
            j = i + 1
            while j < n and _NON_ENGLISH_SCRIPT_RE.match(text[j]):
                j += 1
            yield text[i:j], False
            i = j
            continue
        j = i + 1
        while j < n and not _NON_ENGLISH_SCRIPT_RE.match(text[j]):
            j += 1
        yield text[i:j], True
        i = j


def _join_latin_tokens(parts: list[str]) -> str:
    text = "".join(parts)
    return re.sub(r"\s+", " ", text).strip()


def _prefer_letter_name_in_english(
    surface: str,
    token_idx: int,
    tokens: list[tuple[str, str]],
) -> bool:
    """Whether a lone ``A`` in English text should be read as letter EY1 vs article AH0."""
    if len(surface) != 1 or not surface.isalpha():
        return False
    if surface.upper() != "A":
        return True
    word_indices = [i for i, (kind, _) in enumerate(tokens) if kind == "word"]
    if not word_indices:
        return False
    if len(word_indices) == 1:
        return True
    if token_idx == word_indices[-1]:
        return True
    return False


def _lookup_english_token_phonemes(
    g2p: CMUDictG2P,
    token: str,
    *,
    prefer_letter_name: bool = False,
) -> list[str]:
    if len(token) == 1 and token.isalpha():
        phones, _ = g2p.lookup_isolated_letter_phonemes(
            token, prefer_letter_name=prefer_letter_name
        )
        return phones
    phones, _ = g2p.lookup_phrase_phonemes(token)
    return phones


def _convert_latin_run(
    segment: str,
    g2p: CMUDictG2P,
    *,
    add_sentence_end: bool = False,
) -> str:
    """G2P English words only; pinyin (ni2) and ARPAbet (EY1) pass through."""
    tokens = _tokenize_latin_for_dict_g2p(segment)
    if not any(_latin_token_needs_g2p(token) for token in tokens):
        return segment

    if add_sentence_end and all(
        _latin_token_needs_g2p(token) or _is_punct_token(token)
        for token in tokens
        if token not in _BOUNDARY_TOKENS
    ):
        return english_text_to_slash_arpa(segment, g2p, add_sentence_end=add_sentence_end)

    parts: list[str] = []
    for token in tokens:
        if token in _BOUNDARY_TOKENS:
            parts.append(f" {token} ")
        elif _is_isolated_letter_token(token):
            phones = _lookup_english_token_phonemes(
                g2p, token, prefer_letter_name=True
            )
            if phones:
                _append_slash_arpa_chunk(parts, phones)
            else:
                parts.append(token)
        elif _is_punct_token(token) or _is_pinyin_token(token) or _is_arpabet_like_token(token):
            if parts and not parts[-1].endswith(" "):
                parts.append(" ")
            parts.append(token)
            parts.append(" ")
        elif _is_english_word_token(token):
            phones = _lookup_english_token_phonemes(g2p, token)
            if phones:
                _append_slash_arpa_chunk(parts, phones)
        else:
            parts.append(token)
    return _join_latin_tokens(parts)


def convert_mixed_text_to_slash_arpa(text: str, g2p: CMUDictG2P) -> str:
    """Convert inline English words to slash ARPAbet; keep pinyin/ARPAbet/CJK unchanged."""
    if not has_raw_english_words(text):
        return text

    if not _NON_ENGLISH_SCRIPT_RE.search(text):
        return _convert_latin_run(text, g2p, add_sentence_end=True)

    parts: list[str] = []
    prev_is_latin: bool | None = None
    for segment, is_latin in _iter_mixed_script_segments(text):
        if is_latin:
            converted = _convert_latin_run(segment, g2p).strip()
            if not converted:
                continue
            segment_text = converted
        else:
            segment_text = segment.strip()
            if not segment_text:
                continue

        if parts and prev_is_latin is not None and prev_is_latin != is_latin:
            parts.append("_")
        parts.append(segment_text)
        prev_is_latin = is_latin
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def preprocess_english_input(
    text: str,
    g2p: CMUDictG2P | None = None,
) -> str:
    """Auto-route English input to ARPAbet pass-through or CMUdict G2P."""
    if not text or not text.strip():
        return text

    text = text.strip()
    g2p = g2p or get_default_g2p()

    if is_arpabet_input(text):
        return normalize_arpabet_input(text)

    if has_raw_english_words(text):
        return convert_mixed_text_to_slash_arpa(text, g2p)

    return text


def is_backend_available(cmudict_path: str | Path = DEFAULT_CMUDICT_PATH) -> bool:
    return Path(cmudict_path).is_file()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="English CMUdict frontend")
    parser.add_argument("text", nargs="?", default="CHAP")
    parser.add_argument("--cmudict", type=Path, default=DEFAULT_CMUDICT_PATH)
    parser.add_argument("--supplement", type=Path, default=DEFAULT_SUPPLEMENT_PATH)
    args = parser.parse_args()

    engine = CMUDictG2P.from_paths(args.cmudict, args.supplement)
    print(preprocess_english_input(args.text, engine))
