"""Text cleaners for multi-language pipelines.

Public cleaners:
  - pinyin_direct_mixed_cleaners: auto-routes pinyin Chinese vs ARPAbet English
  - english_direct_phoneme_cleaners: normalizes pre-computed ARPAbet tokens
  - en_zh_dict_mixed_cleaners: hanzi lexicon + English CMUdict G2P + ARPAbet pass-through
    via chinese_lexicon.txt (longest-match), then through the same pinyin → Bopomofo
    path used by training.
  - ar_en_mixed_cleaners: Arabic chars (space-separated) + English ARPAbet
  - ar_en_dict_mixed_cleaners: Arabic chars + English CMUdict G2P + ARPAbet pass-through
  - bn_en_mixed_cleaners: Bengali chars (space-separated) + English ARPAbet
  - en_ru_mixed_cleaners: Russian chars (space-separated) + English ARPAbet
"""

import re
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Dash / hyphen variants shared across symbol sets (see char_symbols/langs/*.py).
_DASH_CHARS = "-—–‐‑"
_TRAILING_PUNCT_RUN_PATTERN = re.compile(
    r"(\s*[^\w\s_]\s*)+$",
    re.UNICODE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
# Structural single quotes (not spoken in TTS); aligned with en-ru cleaner.
_STRUCTURAL_SINGLE_QUOTE_RE = re.compile(r"[''\u2018\u2019\u300e\u300f]")


def _strip_structural_single_quotes(text: str) -> str:
    return _STRUCTURAL_SINGLE_QUOTE_RE.sub("", text)


def _collapse_empty_slash_segments(text: str) -> str:
    """Collapse slash runs emptied by structural punctuation removal."""
    text = re.sub(r"(?:\s*/\s*){2,}", " / ", text)
    return re.sub(r"\s*/\s*$", "", text)


def _remove_dashes(text: str) -> str:
    return text.translate(str.maketrans({ch: " " for ch in _DASH_CHARS}))


def _dedupe_trailing_punctuation(text: str) -> str:
    match = _TRAILING_PUNCT_RUN_PATTERN.search(text)
    if not match:
        return text
    trailing = text[match.start():]
    # "/" and "|" are ARPAbet word separators in mixed cleaners, not sentence punctuation.
    punct_chars = [ch for ch in trailing if not ch.isspace() and ch not in "/|"]
    if len(punct_chars) <= 1:
        return text
    # Only collapse runs of the *same* trailing mark (e.g. "..." → ".", "!!" → "!").
    # Do not merge distinct marks such as `/ " .` in ARPAbet transcripts.
    if len(set(punct_chars)) == 1:
        return text[: match.start()] + punct_chars[0]
    return text


# Sentence-final punctuation that already gives a natural TTS ending (no extra '.').
_ACCEPTABLE_TRAILING_PUNCT = frozenset(
    ",.…!?;:"
    "،؟"  # ar comma / question mark
    "।"  # bn danda (sentence end)
    "。！？；："  # CJK fullwidth sentence punctuation
)


def _ensure_trailing_sentence_punct(text: str) -> str:
    """Append '.' when text lacks sentence-final punctuation (smoother TTS ending)."""
    if not text:
        return text
    stripped = text.rstrip()
    if not stripped:
        return text
    if stripped.endswith("..."):
        return text
    if stripped[-1] in _ACCEPTABLE_TRAILING_PUNCT:
        return text
    return stripped + "."


def preprocess_text(text: str) -> str:
    """Common pre-cleaning for all language cleaners before tokenization."""
    if not text:
        return ""
    text = _strip_structural_single_quotes(text)
    text = _collapse_empty_slash_segments(text)
    text = _remove_dashes(text)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    text = _dedupe_trailing_punctuation(text)
    return _ensure_trailing_sentence_punct(text)

# ==============================================================================
# English ARPAbet cleaner
# ==============================================================================

def english_direct_phoneme_cleaners(text):
    """Normalize precomputed English phoneme text into token sequence.

    Input:  "DH EH1 R / IH1 Z / M AH0 S Y ER1"
    Output: "DH EH1 R _ IH1 Z _ M AH0 S Y ER1"
    """
    if not text:
        return ""

    normalized = re.sub(r"\s+", " ", text.strip())
    normalized = re.sub(r"\s*[|/]\s*", " _ ", normalized)
    return normalized


# ==============================================================================
# Pinyin → Bopomofo conversion
# ==============================================================================

_pinyin_2_bpmf_cache = None
_pinyin_tone_dict = {"0": "˙", "5": "˙", "6": "ˊ", "1": "ˉ", "2": "ˊ", "3": "ˇ", "4": "ˋ"}
_pinyin_tone_chars = frozenset(_pinyin_tone_dict)
_pinyin_syllable_re = re.compile(r"^[a-z]+[0-6]$")
_pinyin_syllable_scan_re = re.compile(r"[a-z]+[0-6]")
_arpabet_token_re = re.compile(r"^[A-Z]{1,3}[012]?$")
_arpabet_token_scan_re = re.compile(r"[A-Z]{1,3}[012]?")

# Chinese / fullwidth punctuation → halfwidth (for space-separated pinyin+ punct input).
_ZH_PUNCT_TO_HALF = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "！": "!",
        "？": "?",
        "、": ",",
        "；": ";",
        "：": ":",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "「": '"',
        "」": '"',
        "『": "'",
        "』": "'",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": "<",
        "》": ">",
        "—": "-",
        "–": "-",
        "‐": "-",
        "·": ".",
        "﹐": ",",
        "﹒": ".",
        "﹖": "?",
        "﹗": "!",
        "．": ".",
    }
)
_HALFWIDTH_PUNCT_CHARS = frozenset(",.!?;:\"()[]<>-")
_ELLIPSIS_CHAR = "…"
_ELLIPSIS_ALIASES = ("...", "⋯", "···", "・・・")


def _normalize_ellipsis(text: str) -> str:
    """Collapse ellipsis variants to a single U+2026 character."""
    for alias in _ELLIPSIS_ALIASES:
        text = text.replace(alias, _ELLIPSIS_CHAR)
    return text


def _normalize_zh_punct_to_halfwidth(text: str) -> str:
    """Map CJK punctuation to halfwidth; ellipsis stays as single ``…`` token."""
    if not text:
        return text
    text = _normalize_ellipsis(text)
    text = unicodedata.normalize("NFKC", text)
    text = _normalize_ellipsis(text)
    text = text.translate(_ZH_PUNCT_TO_HALF)
    return _strip_structural_single_quotes(text)


def _canonical_punctuation_token(token: str) -> str | None:
    """Return one output punctuation character/token, or None if not punctuation."""
    if not token:
        return None
    if token == _ELLIPSIS_CHAR or token in _ELLIPSIS_ALIASES:
        return _ELLIPSIS_CHAR
    if all(ch in _HALFWIDTH_PUNCT_CHARS for ch in token):
        return token
    return None


def _is_punctuation_token(token: str) -> bool:
    return _canonical_punctuation_token(token) is not None


def _is_zh_punct_char(ch: str) -> bool:
    """Single-character punctuation after halfwidth normalization."""
    return ch == _ELLIPSIS_CHAR or ch in _HALFWIDTH_PUNCT_CHARS


def _tokenize_mixed_pinyin_text(text: str) -> list[str]:
    """Split space-separated or glued pinyin/ARPAbet/punctuation into tokens.

    Fullwidth punctuation is normalized to halfwidth first.  Pinyin syllables
    glued to punctuation (e.g. ``ni3,hao3`` or ``shi4 jie4.``) are split apart.
    """
    text = _normalize_zh_punct_to_halfwidth(text)
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in ("_", "/", "|"):
            tokens.append(ch)
            i += 1
            continue
        if _is_zh_punct_char(ch):
            tokens.append(ch)
            i += 1
            continue
        if "A" <= ch <= "Z":
            m = _arpabet_token_scan_re.match(text, i)
            if m and m.start() == i:
                tokens.append(m.group())
                i = m.end()
                continue
        if "a" <= ch <= "z":
            m = _pinyin_syllable_scan_re.match(text, i)
            if m and m.start() == i:
                tokens.append(m.group())
                i = m.end()
                continue
        tokens.append(ch)
        i += 1
    return tokens


def _append_punctuation_tokens(result_tokens: list[str], token: str) -> None:
    """Emit punctuation into the phoneme stream (with ``_`` boundaries)."""
    punct = _canonical_punctuation_token(token)
    if punct is None:
        return
    if len(punct) == 1:
        chars = [punct]
    else:
        chars = [ch for ch in punct if ch in _HALFWIDTH_PUNCT_CHARS]
    for ch in chars:
        if result_tokens and result_tokens[-1] != "_":
            result_tokens.append("_")
        result_tokens.append(ch)
        result_tokens.append("_")


def _pinyin_syllable_tone(syllable: str):
    if len(syllable) >= 2 and syllable[-1] in _pinyin_tone_chars:
        return syllable[-1]
    return None


def _set_pinyin_syllable_tone(syllable: str, tone: str) -> str:
    if _pinyin_syllable_tone(syllable) is not None:
        return syllable[:-1] + tone
    return syllable + tone


def _apply_third_tone_sandhi(syllables):
    """三三变调：连续两个三声时，前一个改为二声（与训练数据一致）。"""
    if len(syllables) < 2:
        return syllables
    result = list(syllables)
    for i in range(len(result) - 1):
        if _pinyin_syllable_tone(result[i]) == "3" and _pinyin_syllable_tone(result[i + 1]) == "3":
            result[i] = _set_pinyin_syllable_tone(result[i], "2")
    return result


def _apply_third_tone_sandhi_to_tokens(tokens: list[str]) -> list[str]:
    """Apply 三三变调 on pinyin syllables (ARPAbet / punctuation tokens unchanged)."""
    if len(tokens) < 2:
        return tokens
    pinyin_indices = []
    pinyin_syllables = []
    for i, tok in enumerate(tokens):
        if _pinyin_syllable_re.match(tok):
            pinyin_indices.append(i)
            pinyin_syllables.append(tok)
    if len(pinyin_syllables) < 2:
        return tokens
    adjusted = _apply_third_tone_sandhi(pinyin_syllables)
    out = list(tokens)
    for idx, syllable in zip(pinyin_indices, adjusted):
        out[idx] = syllable
    return out


def _load_pinyin_2_bpmf():
    global _pinyin_2_bpmf_cache
    if _pinyin_2_bpmf_cache is not None:
        return _pinyin_2_bpmf_cache
    pinyin_file = REPO_ROOT / "lits" / "text" / "sources" / "pinyin_2_bpmf.txt"
    mapping = {}
    with open(pinyin_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                mapping[parts[0]] = parts[1]
    _pinyin_2_bpmf_cache = mapping
    return mapping


def _ensure_boundary_after_arpabet(result_tokens: list[str]) -> None:
    """Insert ``_`` when an ARPAbet phoneme is immediately followed by pinyin."""
    if result_tokens and _is_arpabet_token(result_tokens[-1]):
        result_tokens.append("_")


def _pinyin_to_bopomofo_tokens(text, apply_third_tone: bool = True):
    """Convert pinyin+ARPAbet mixed string to space-delimited tokens.

    Pinyin syllables are converted to Bopomofo char tokens with ``_``
    boundaries; ARPAbet phonemes pass through unchanged. A ``_`` is inserted
    between the last ARPAbet phoneme of an English unit and the next pinyin
    syllable when the input line omits an explicit boundary.
    Halfwidth punctuation tokens (e.g. ``,``, ``.``) are kept in the output.

    Input:  "ni3 hao3 _ DH IH1 S"
    Output: "ㄋ ㄧ ˇ _ ㄏ ㄠ ˇ _ DH IH1 S"
    Input:  "EY1 yi1"
    Output: "EY1 _ ㄧ ˉ"
    Input:  "ni3 hao3 , shi4 jie4 ."
    Output: "ㄋ ㄧ ˇ _ ㄏ ㄠ ˇ _ , _ ㄕ ˋ _ ㄐ ㄧ ㄝ ˋ _ ."
    Input:  "ni3,hao3 shi4 jie4."
    Output: same as spaced punctuation form above.
    """
    tokens = _tokenize_mixed_pinyin_text(text)
    if apply_third_tone:
        tokens = _apply_third_tone_sandhi_to_tokens(tokens)
    pinyin_2_bpmf = _load_pinyin_2_bpmf()

    result_tokens = []
    for syllable in tokens:
        if not syllable:
            continue
        if syllable in ("_", "/", "|"):
            if not result_tokens or result_tokens[-1] != "_":
                result_tokens.append("_")
            continue
        if _is_punctuation_token(syllable):
            _append_punctuation_tokens(result_tokens, syllable)
            continue
        if _is_arpabet_token(syllable):
            result_tokens.append(syllable)
            continue
        if len(syllable) >= 2 and syllable[-1] in _pinyin_tone_dict:
            _ensure_boundary_after_arpabet(result_tokens)
            tone = syllable[-1]
            base = syllable[:-1]
            if base in pinyin_2_bpmf:
                bpmf = pinyin_2_bpmf[base]
                for ch in bpmf:
                    result_tokens.append(ch)
                result_tokens.append(_pinyin_tone_dict[tone])
                result_tokens.append("_")
                continue
            if len(base) > 1 and base.endswith("r") and base[:-1] in pinyin_2_bpmf:
                _ensure_boundary_after_arpabet(result_tokens)
                bpmf = pinyin_2_bpmf[base[:-1]]
                for ch in bpmf:
                    result_tokens.append(ch)
                result_tokens.append(_pinyin_tone_dict[tone])
                result_tokens.append("_")
                result_tokens.append("ㄦ")
                result_tokens.append("˙")
                result_tokens.append("_")
                continue
        # Non-pinyin token (ARPAbet phoneme, etc.): pass through as-is
        result_tokens.append(syllable)

    while result_tokens and result_tokens[-1] == "_":
        result_tokens.pop()
    return " ".join(result_tokens)


# ==============================================================================
# Main hybrid cleaner
# ==============================================================================


def _is_arpabet_token(token: str) -> bool:
    """Training English uses uppercase ARPAbet (e.g. ER0, DH); pinyin is lowercase (ni3)."""
    return bool(_arpabet_token_re.match(token))


def pinyin_direct_mixed_cleaners(text):
    """Hybrid cleaner for zh-en training with pinyin Chinese + ARPAbet English.

    Handles pure pinyin, pure ARPAbet, and mixed pinyin+ARPAbet text.
    Pinyin tokens are converted to Bopomofo; ARPAbet tokens pass through.
    Chinese punctuation in the pinyin line (e.g. from add_punct_to_pinyin) is
    normalized to halfwidth and emitted as punctuation tokens in the output.

    Chinese input (pinyin):  "ni3 hao3 shi4 jie4"
    With punctuation:        "ni3 hao3 , shi4 jie4 ."
    English input (ARPAbet): "DH AE1 T / W ER1 L D"
    Mixed input:             "ni3 hao3 _ DH IH1 S"
    """
    if not text:
        return ""
    return _pinyin_to_bopomofo_tokens(text)


# ==============================================================================
# Chinese hanzi (character) cleaner — raw 汉字 input
# ==============================================================================

_chinese_frontend = None
_en_tokenizer = None
_chinese_lexicon_cache = None


def _get_chinese_frontend():
    global _chinese_frontend
    if _chinese_frontend is not None:
        return _chinese_frontend
    from lits.text.g2p.mandarin import Frontend_chinese
    resource_path = str(REPO_ROOT / "lits" / "text")
    _chinese_frontend = Frontend_chinese(resource_path, BLANK_LEVEL=2)
    return _chinese_frontend


def _get_en_tokenizer():
    global _en_tokenizer
    if _en_tokenizer is not None:
        return _en_tokenizer
    from lits.text.g2p.text_tokenizers import TextTokenizer
    _en_tokenizer = TextTokenizer(language="en-us")
    return _en_tokenizer


def _load_chinese_lexicon():
    """Load chinese_lexicon.txt (+ optional user_dict.txt) for hanzi G2P."""
    global _chinese_lexicon_cache
    if _chinese_lexicon_cache is not None:
        return _chinese_lexicon_cache

    word_pinyin_dict: dict[str, str] = {}
    user_word_set: set[str] = set()
    lexicon_file = REPO_ROOT / "lits" / "text" / "sources" / "chinese_lexicon.txt"
    with open(lexicon_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) == 2:
                word_pinyin_dict[parts[0]] = parts[1]

    user_dict_file = REPO_ROOT / "lits" / "text" / "sources" / "user_dict.txt"
    if user_dict_file.exists():
        with open(user_dict_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    word_pinyin_dict[parts[0]] = parts[-1]
                    user_word_set.add(parts[0])

    poly_dict: set[str] = set()
    poly_file = REPO_ROOT / "lits" / "text" / "sources" / "polychar.txt"
    if poly_file.exists():
        with open(poly_file, "r", encoding="utf-8") as f:
            for line in f:
                word = line.strip()
                if word:
                    poly_dict.add(word)

    _chinese_lexicon_cache = {
        "word_pinyin_dict": word_pinyin_dict,
        "user_word_set": user_word_set,
        "poly_dict": poly_dict,
        "max_word_len": max((len(w) for w in word_pinyin_dict), default=1),
        "max_user_word_len": max((len(w) for w in user_word_set), default=1),
    }
    return _chinese_lexicon_cache


def _normalize_lexicon_pinyin(pinyin: str) -> list[str]:
    syllables = []
    for py in pinyin.strip().split():
        py = py.replace("ü", "v").replace("Ü", "v")
        if _pinyin_syllable_re.match(py):
            syllables.append(py)
    return syllables


def _candidate_conflicts_with_contextual_polyphone(cand: str, pinyin: str) -> bool:
    """Reject lexicon matches whose first polyphone contradicts contextual G2P.

    The lexicon is used for greedy longest-match segmentation, but it contains
    rare entries such as ``的情 -> di2 qing2``.  In normal phrases like
    ``...的情况`` that match incorrectly swallows the structural particle ``的``.
    Use pypinyin as a lightweight contextual check for this high-impact
    polyphonic prefix instead of adding phrase-specific overrides.
    """
    if len(cand) <= 1 or not cand.startswith("的"):
        return False

    lexicon_syllables = _normalize_lexicon_pinyin(pinyin)
    if not lexicon_syllables:
        return False

    contextual = _pypinyin_syllables_for_text(cand)
    if not contextual:
        return False

    return lexicon_syllables[0] != contextual[0]


def _segment_hanzi_with_lexicon(text: str, lexicon: dict) -> list[str]:
    """Greedy longest-match segmentation using chinese_lexicon.txt."""
    word_pinyin_dict = lexicon["word_pinyin_dict"]
    max_word_len = lexicon["max_word_len"]
    user_word_set = lexicon.get("user_word_set", set())
    max_user_word_len = lexicon.get("max_user_word_len", 1)
    words: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        matched = None
        for length in range(min(max_user_word_len, n - i), 1, -1):
            cand = text[i:i + length]
            if cand in user_word_set:
                matched = cand
                break
        for length in range(min(max_word_len, n - i), 1, -1):
            if matched is not None:
                break
            cand = text[i:i + length]
            if cand in word_pinyin_dict:
                overlaps_user_word = False
                for user_start in range(i + 1, i + length):
                    max_inner_len = min(max_user_word_len, n - user_start)
                    for user_len in range(max_inner_len, 1, -1):
                        if text[user_start:user_start + user_len] in user_word_set:
                            overlaps_user_word = True
                            break
                    if overlaps_user_word:
                        break
                if overlaps_user_word:
                    continue
                if _candidate_conflicts_with_contextual_polyphone(cand, word_pinyin_dict[cand]):
                    continue
                matched = cand
                break
        if matched is not None:
            words.append(matched)
            i += len(matched)
        else:
            words.append(text[i])
            i += 1
    return words


def _pypinyin_syllables_for_text(hanzi_text: str) -> list[str]:
    from pypinyin import Style, pinyin

    syllables = []
    for item in pinyin(
        hanzi_text.strip(),
        style=Style.TONE3,
        neutral_tone_with_five=True,
        errors=lambda chars: list(chars),
    ):
        token = item[0].strip()
        if not token:
            continue
        token = token.replace("ü", "v").replace("Ü", "v")
        if _pinyin_syllable_re.match(token):
            syllables.append(token)
    return syllables


def _lexicon_pinyin_for_word(word: str, lexicon: dict) -> list[str] | None:
    """Resolve one segmented hanzi word to numbered pinyin syllables."""
    word_pinyin_dict = lexicon["word_pinyin_dict"]
    user_word_set = lexicon.get("user_word_set", set())
    poly_dict = lexicon["poly_dict"]

    if word in word_pinyin_dict and (word in user_word_set or word not in poly_dict):
        syllables = _normalize_lexicon_pinyin(word_pinyin_dict[word])
        if syllables:
            return syllables

    syllables: list[str] = []
    for ch in word:
        if ch in word_pinyin_dict:
            part = _normalize_lexicon_pinyin(word_pinyin_dict[ch])
            if not part:
                return None
            syllables.extend(part)
        else:
            return None
    return syllables


_bpmf_base_to_pinyin_cache = None
_BPMF_TONE_TO_NUMBER = {"ˉ": "1", "ˊ": "2", "ˇ": "3", "ˋ": "4", "˙": "5"}


def _get_bpmf_base_to_pinyin() -> dict[str, str]:
    global _bpmf_base_to_pinyin_cache
    if _bpmf_base_to_pinyin_cache is not None:
        return _bpmf_base_to_pinyin_cache
    mapping = {bpmf: py for py, bpmf in _load_pinyin_2_bpmf().items()}
    _bpmf_base_to_pinyin_cache = mapping
    return mapping


def _bopomofo_syllable_to_numbered_pinyin(bopomofo: str) -> str | None:
    """Convert one numbered-pinyin-style bopomofo syllable back to e.g. yi4."""
    if not bopomofo:
        return None
    tone = "1"
    body = bopomofo
    if body[-1] in _BPMF_TONE_TO_NUMBER:
        tone = _BPMF_TONE_TO_NUMBER[body[-1]]
        body = body[:-1]
    py_base = _get_bpmf_base_to_pinyin().get(body)
    if py_base is None:
        return None
    return f"{py_base}{tone}"


def _apply_mandarin_tone_sandhi(hanzi_text: str, syllables: list[str]) -> list[str]:
    """Apply bu/yi/er tone sandhi from Frontend_chinese (mandarin.py)."""
    if not hanzi_text or not syllables or len(hanzi_text) != len(syllables):
        return syllables

    frontend = _get_chinese_frontend()
    bopomofos: list[str] = []
    erhua_tails: list[list[str]] = []
    for py in syllables:
        parts = frontend._pinyin_to_bopomofos(py)
        if parts is None:
            return syllables
        bopomofos.append(parts[0])
        erhua_tails.append(parts[1:])

    bopomofos = frontend.bu_sandhi(hanzi_text, bopomofos)
    bopomofos = frontend.yi_sandhi(hanzi_text, bopomofos)
    bopomofos = frontend.er_sandhi(hanzi_text, bopomofos)

    adjusted: list[str] = []
    for bpmf, tail, orig_py in zip(bopomofos, erhua_tails, syllables):
        converted = _bopomofo_syllable_to_numbered_pinyin(bpmf)
        if converted is None:
            adjusted.append(orig_py)
            continue
        if tail:
            base, tone = converted[:-1], converted[-1]
            converted = f"{base}r{tone}"
        adjusted.append(converted)
    return adjusted


def _hanzi_chunk_to_pinyin_syllables(hanzi_text: str) -> list[str]:
    """Convert a hanzi-only run to numbered pinyin syllables via chinese_lexicon.txt."""
    hanzi_text = hanzi_text.strip()
    if not hanzi_text:
        return []

    lexicon = _load_chinese_lexicon()
    words = _segment_hanzi_with_lexicon(hanzi_text, lexicon)
    frontend = _get_chinese_frontend()
    words = frontend.merge_yi(words)
    words = frontend.merge_bu(words)
    words = frontend.merge_er(words)

    syllables: list[str] = []
    for word in words:
        word_syllables = _lexicon_pinyin_for_word(word, lexicon)
        if word_syllables is None:
            syllables.extend(_pypinyin_syllables_for_text(word))
        else:
            syllables.extend(word_syllables)

    hanzi_flat = "".join(words)
    syllables = _apply_third_tone_sandhi(syllables)
    syllables = _apply_mandarin_tone_sandhi(hanzi_flat, syllables)
    return _restore_user_override_syllables(hanzi_flat, syllables, lexicon)


def _restore_user_override_syllables(hanzi_text: str, syllables: list[str], lexicon: dict) -> list[str]:
    """Keep explicit user-dictionary pinyin literal after global tone sandhi."""
    if not hanzi_text or len(hanzi_text) != len(syllables):
        return syllables
    word_pinyin_dict = lexicon["word_pinyin_dict"]
    user_word_set = lexicon.get("user_word_set", set())
    if not user_word_set:
        return syllables

    output = list(syllables)
    occupied = [False] * len(output)
    for word in sorted(user_word_set, key=len, reverse=True):
        if len(word) <= 1:
            continue
        word_syllables = _normalize_lexicon_pinyin(word_pinyin_dict.get(word, ""))
        if len(word_syllables) != len(word):
            continue
        start = hanzi_text.find(word)
        while start >= 0:
            end = start + len(word)
            if not any(occupied[start:end]):
                output[start:end] = word_syllables
                for index in range(start, end):
                    occupied[index] = True
            start = hanzi_text.find(word, start + 1)
    return output


def _split_hanzi_and_non_hanzi_runs(text: str) -> list[tuple[str, bool]]:
    """Split a no-space chunk into hanzi and non-hanzi runs.

    The mixed English frontend may emit ARPAbet directly next to hanzi, e.g.
    ``成S AH1`` or ``把D EH1``. Keeping that as one hanzi chunk drops the
    adjacent ARPAbet token when pypinyin handles the chunk.
    """
    runs: list[tuple[str, bool]] = []
    start = 0
    current_is_hanzi = bool(_hanzi_char_re.match(text[0])) if text else False
    for idx, ch in enumerate(text[1:], 1):
        is_hanzi = bool(_hanzi_char_re.match(ch))
        if is_hanzi != current_is_hanzi:
            runs.append((text[start:idx], current_is_hanzi))
            start = idx
            current_is_hanzi = is_hanzi
    if text:
        runs.append((text[start:], current_is_hanzi))
    return runs


def _hanzi_to_bopomofo_tokens(text):
    """Convert raw Chinese characters through numbered pinyin to Bopomofo tokens.

    Hanzi segments are segmented with chinese_lexicon.txt (longest match), then
    resolved to numbered pinyin from the same lexicon; unknown chars fall back to
    pypinyin.  Output follows the same pinyin-to-Bopomofo path as direct input.
    Punctuation (fullwidth or halfwidth) is normalized to halfwidth and preserved.
    """
    if not text:
        return ""

    text = _normalize_zh_punct_to_halfwidth(text.strip())
    token_parts: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if _is_zh_punct_char(ch):
            token_parts.append(ch)
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace() and not _is_zh_punct_char(text[j]):
            j += 1
        chunk = text[i:j]
        if _hanzi_char_re.search(chunk):
            for sub_chunk, is_hanzi in _split_hanzi_and_non_hanzi_runs(chunk):
                if is_hanzi:
                    token_parts.extend(_hanzi_chunk_to_pinyin_syllables(sub_chunk))
                else:
                    token_parts.extend(_tokenize_mixed_pinyin_text(sub_chunk))
        else:
            token_parts.extend(_tokenize_mixed_pinyin_text(chunk))
        i = j

    return _pinyin_to_bopomofo_tokens(" ".join(token_parts), apply_third_tone=False)


_hanzi_char_re = re.compile(r"[\u4e00-\u9fff]")
_english_word_re = re.compile(r"[A-Za-z]+(?:['''-][A-Za-z]+)*")


def _segment_zh_en(text):
    """Split mixed text into (segment, lang) pairs: 'zh' or 'en'."""
    segments = []
    i = 0
    n = len(text)
    while i < n:
        if re.match(r"[A-Za-z]", text[i]):
            m = _english_word_re.match(text, i)
            if m:
                segments.append((m.group(), "en"))
                i = m.end()
            else:
                segments.append((text[i], "other"))
                i += 1
        else:
            j = i
            while j < n and not re.match(r"[A-Za-z]", text[j]):
                j += 1
            segments.append((text[i:j], "zh"))
            i = j
    return segments


def en_zh_dict_mixed_cleaners(text):
    """Hybrid cleaner: hanzi lexicon lookup + English CMUdict G2P + ARPAbet pass-through.

    Implementation lives in temp_cmu_g2p.
    """
    from temp_cmu_g2p.mixed_cleaners import en_zh_dict_mixed_cleaners as _impl
    return _impl(text)


def chinese_cleaners(text, phonemize=True):
    """Normalize Chinese text (number/symbol expansion). Used by mixed pipeline."""
    try:
        from lits.text.g2p.cn2an_transform import chinese_to_num
        text = chinese_to_num(text)
    except ImportError:
        pass
    text = re.sub(r"[\u201c\u201d\u300a\u300b\u3010\u3011]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def english_cleaners(text, phonemize=True):
    """Normalize English text (casing, whitespace). Used by mixed pipeline."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text
    return english_direct_phoneme_cleaners(text)


# ==============================================================================
# Utility
# ==============================================================================

def _spaces_to_underscores(text):
    return re.sub(r"\s+", "_", text).strip("_")


def _append_punct_boundary(result: list[str], ch: str) -> None:
    if result and result[-1] != "_":
        result.append("_")
    result.append(ch)
    result.append("_")


def _emit_native_token(result: list[str], token: str, is_punct_char) -> None:
    """Expand a native-script token; glued punctuation gets ``_`` boundaries."""
    segment: list[str] = []
    for ch in token:
        if is_punct_char(ch):
            if segment:
                result.extend(segment)
                result.append("_")
                segment = []
            _append_punct_boundary(result, ch)
        else:
            segment.append(ch)
    if segment:
        result.extend(segment)
        result.append("_")


def _run_mixed_native_cleaner(
    text: str,
    *,
    normalize,
    native_re,
    is_punct_char,
) -> str:
    if not text:
        return ""

    text = normalize(text)
    result = []
    prev_type = None  # 'native', 'arpa', or None
    for token in text.strip().split():
        if token in ("/", "|"):
            if not result or result[-1] != "_":
                result.append("_")
            prev_type = None
        elif native_re.search(token):
            if prev_type == "arpa" and result and result[-1] != "_":
                result.append("_")
            _emit_native_token(result, token, is_punct_char)
            prev_type = "native"
        elif all(is_punct_char(ch) for ch in token):
            if prev_type == "arpa" and result and result[-1] != "_":
                result.append("_")
            for ch in token:
                _append_punct_boundary(result, ch)
            prev_type = "native"
        else:
            if prev_type == "native" and result and result[-1] != "_":
                result.append("_")
            result.append(token.upper())
            prev_type = "arpa"

    while result and result[-1] == "_":
        result.pop()
    return " ".join(result)


# ==============================================================================
# Arabic cleaners
# ==============================================================================

_AR_RE = re.compile(r"[\u0600-\u06ff]")
_BN_RE = re.compile(r"[\u0980-\u09ff]")
_RU_RE = re.compile(r"[\u0400-\u04ff\u0300-\u0301]")
_AR_CHAR_MAP = str.maketrans(
    {
        "\u06cc": "\u064a",  # ی (Persian yeh) → ي (Arabic yeh)
        "\u06a9": "\u0643",  # ک (Persian kaf) → ك (Arabic kaf)
        "\u0640": None,  # ـ (tatweel) → delete
    }
)


def _normalize_arabic(text):
    if not text:
        return text
    text = text.translate(_AR_CHAR_MAP)
    return _strip_structural_single_quotes(text)


# Matches lits/text/char_symbols/langs/ar_en.py punctuation (excluding space).
_AR_PUNCT_CHARS = frozenset(
    "،؛؟;:,.!?¡¿—…\"«»""''–-٪×÷+*=%^°()/"
)


def _is_ar_punct_char(ch: str) -> bool:
    return ch in _AR_PUNCT_CHARS


def ar_en_mixed_cleaners(text):
    """Hybrid ar-en cleaner: Arabic chars (space-separated) + English ARPAbet tokens.

    Token-level detection: each space-separated token is checked for Arabic
    characters.  Arabic tokens are normalized (Persian ی/ک → Arabic ي/ك,
    tatweel removed) then exploded into per-char tokens; glued punctuation
    is split with ``_`` boundaries (same convention as Chinese cleaners).
    ARPA tokens (e.g. IH1, DH) pass through unchanged.
    """
    return _run_mixed_native_cleaner(
        text,
        normalize=_normalize_arabic,
        native_re=_AR_RE,
        is_punct_char=_is_ar_punct_char,
    )


def ar_en_dict_mixed_cleaners(text):
    """Hybrid ar-en cleaner: Arabic chars + English CMUdict G2P + ARPAbet pass-through.

    Implementation lives in temp_cmu_g2p.
    """
    from temp_cmu_g2p.mixed_cleaners import ar_en_dict_mixed_cleaners as _impl
    return _impl(text)


def _normalize_bengali(text):
    if not text:
        return text
    text = unicodedata.normalize("NFC", text)
    return _strip_structural_single_quotes(text)


# Matches lits/text/char_symbols/langs/bn_en.py punctuation (excluding space).
_BN_PUNCT_CHARS = frozenset(
    "।;:,.!?¡¿—…\"«»""''–-٪×÷+*=%^°()/"
)


def _is_bn_punct_char(ch: str) -> bool:
    return ch in _BN_PUNCT_CHARS


def bn_en_mixed_cleaners(text):
    """Hybrid bn-en cleaner: Bengali chars (space-separated) + English ARPAbet tokens.

    Token-level detection: each space-separated token is checked for Bengali
    characters.  Bengali tokens go through NFC normalization then per-char
    tokenization; glued punctuation is split with ``_`` boundaries.
    ARPA tokens pass through unchanged.
    """
    return _run_mixed_native_cleaner(
        text,
        normalize=_normalize_bengali,
        native_re=_BN_RE,
        is_punct_char=_is_bn_punct_char,
    )


# ==============================================================================
# Russian cleaners
# ==============================================================================

# Structural punctuation (quotes, parentheses) — not spoken in Russian TTS.
_RU_STRUCTURAL_PUNCT_RE = re.compile(
    r'[«»„“”‘’\'\"\(\)]'
)
_RU_SENTENCE_PUNCT_DEDUP_RE = re.compile(r"([,.!?;:])\1+")

def _normalize_russian(text):
    if not text:
        return text
    text = unicodedata.normalize("NFC", text)
    while "--" in text:
        text = text.replace("--", "-")
    text = _RU_STRUCTURAL_PUNCT_RE.sub("", text)
    text = _normalize_ellipsis(text)
    text = _RU_SENTENCE_PUNCT_DEDUP_RE.sub(r"\1", text)
    return text


# Matches lits/text/char_symbols/langs/en_ru.py punctuation (excluding space).
_RU_PUNCT_CHARS = frozenset(
    ";:,.!?¡¿…٪×÷+*=%^°/"
)


def _is_ru_punct_char(ch: str) -> bool:
    return ch in _RU_PUNCT_CHARS


def en_ru_mixed_cleaners(text):
    """Hybrid en-ru cleaner: Russian chars (space-separated) + English ARPAbet tokens.

    Token-level detection: each space-separated token is checked for Cyrillic
    characters.  Russian tokens go through NFC normalization then per-char
    tokenization; glued punctuation is split with ``_`` boundaries.
    ARPA tokens pass through unchanged.  Structural punctuation (quotes,
    parentheses) is stripped; sentence punctuation is deduplicated.
    """
    return _run_mixed_native_cleaner(
        text,
        normalize=_normalize_russian,
        native_re=_RU_RE,
        is_punct_char=_is_ru_punct_char,
    )
