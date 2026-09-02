"""Arabic diacritic (tashkeel) detection for ar-en data validation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Harakat + extended Arabic tashkil marks (broader than ar_en.py symbol subset).
_ARABIC_DIACRITIC_RE = re.compile(
    r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e4\u06e7\u06e8\u06ea-\u06ed]"
)
_ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06ff]")


def contains_arabic_script(text: str) -> bool:
    return bool(_ARABIC_SCRIPT_RE.search(text))


def contains_arabic_diacritics(text: str) -> bool:
    return bool(_ARABIC_DIACRITIC_RE.search(text))


def strip_arabic_diacritics(text: str) -> str:
    return _ARABIC_DIACRITIC_RE.sub("", text)


def iter_arabic_tokens(text: str) -> Iterable[str]:
    for token in text.split():
        if contains_arabic_script(token):
            yield token


def build_skeleton_form_index(texts: Iterable[str]) -> dict[str, set[str]]:
    """Map each consonant skeleton to the set of vocalized surface forms in the corpus."""
    index: dict[str, set[str]] = {}
    for text in texts:
        for word in iter_arabic_tokens(text):
            skeleton = strip_arabic_diacritics(word)
            if not skeleton:
                continue
            index.setdefault(skeleton, set()).add(word)
    return index


def is_ambiguous_skeleton(skeleton: str, skeleton_map: dict[str, set[str]]) -> bool:
    return len(skeleton_map.get(skeleton, set())) > 1


def build_partial_text(
    text_no_diac: str,
    text_with_diac: str,
    skeleton_map: dict[str, set[str]],
) -> str:
    """Keep tashkil only on tokens whose skeleton is ambiguous in the vocalized corpus."""

    def vocalize_token(token_no: str, token_with: str) -> str:
        if not contains_arabic_script(token_with):
            return token_no
        skeleton = strip_arabic_diacritics(token_with)
        if is_ambiguous_skeleton(skeleton, skeleton_map):
            return token_with
        return token_no

    tokens_no = text_no_diac.split()
    tokens_with = text_with_diac.split()
    if len(tokens_no) == len(tokens_with):
        return " ".join(vocalize_token(t_no, t_with) for t_no, t_with in zip(tokens_no, tokens_with))

    return " ".join(
        token_with
        if contains_arabic_script(token_with)
        and is_ambiguous_skeleton(strip_arabic_diacritics(token_with), skeleton_map)
        else strip_arabic_diacritics(token_with)
        for token_with in tokens_with
    )


def classify_arabic_diacritics_level(text: str) -> str:
    """Classify row as ``none``, ``partial``, or ``full`` based on Arabic tokens."""
    arabic_tokens = [token for token in text.split() if contains_arabic_script(token)]
    if not arabic_tokens:
        return "none"
    vocalized = sum(1 for token in arabic_tokens if contains_arabic_diacritics(token))
    if vocalized == 0:
        return "none"
    if vocalized == len(arabic_tokens):
        return "full"
    return "partial"


def sentence_skeleton_ambiguity_score(
    text_no_diac: str,
    skeleton_map: dict[str, set[str]],
) -> int:
    """Score a sentence by how ambiguous its Arabic tokens are in the vocalized corpus.

    For each unique Arabic skeleton appearing in ``text_no_diac``, add the number of
    distinct vocalized forms that skeleton takes in ``skeleton_map``.  Skeletons with
    only one known vocalized form contribute 0.
    """
    score = 0
    seen: set[str] = set()
    for word in iter_arabic_tokens(text_no_diac):
        skeleton = strip_arabic_diacritics(word)
        if not skeleton or skeleton in seen:
            continue
        seen.add(skeleton)
        forms = skeleton_map.get(skeleton, set())
        if is_ambiguous_skeleton(skeleton, skeleton_map):
            score += len(forms)
    return score


DiacriticsMode = bool | str


def resolve_use_diacritics(cleaners: list[str], cfg_value: bool | str | None) -> DiacriticsMode | None:
    """Return diacritics expectation for ar-en, or None to skip the check."""
    if not any(
        name in cleaners
        for name in ("ar_en_mixed_cleaners", "ar_en_dict_mixed_cleaners")
    ):
        return None
    if cfg_value is None:
        return False
    if isinstance(cfg_value, str) and cfg_value.lower() == "mixed":
        return "mixed"
    return bool(cfg_value)


@dataclass
class DiacriticsIssue:
    line_no: int
    filepath: str
    text: str
    reason: str


def _check_row(line_no: int, filepath: str, text: str, *, use_diacritics: bool) -> DiacriticsIssue | None:
    has_arabic = contains_arabic_script(text)
    has_diacritics = contains_arabic_diacritics(text)

    if not use_diacritics and has_diacritics:
        return DiacriticsIssue(
            line_no=line_no,
            filepath=filepath,
            text=text,
            reason="unexpected Arabic diacritics (use_diacritics=false)",
        )

    if use_diacritics and has_arabic and not has_diacritics:
        return DiacriticsIssue(
            line_no=line_no,
            filepath=filepath,
            text=text,
            reason="Arabic text without diacritics (use_diacritics=true)",
        )
    return None


def validate_mixed_diacritics_rows(rows: list[tuple[int, str, str]]) -> list[DiacriticsIssue]:
    """Ensure a mixed filelist contains no-, partial-, and full-diacritics Arabic rows."""
    issues: list[DiacriticsIssue] = []
    levels: set[str] = set()

    for _, _, text in rows:
        if not contains_arabic_script(text):
            continue
        levels.add(classify_arabic_diacritics_level(text))

    if not levels:
        issues.append(
            DiacriticsIssue(
                line_no=0,
                filepath="",
                text="",
                reason="no Arabic script found in filelist (use_diacritics=mixed)",
            )
        )
        return issues

    for required in ("none", "partial", "full"):
        if required not in levels:
            issues.append(
                DiacriticsIssue(
                    line_no=0,
                    filepath="",
                    text="",
                    reason=f"mixed filelist missing {required}-diacritics rows",
                )
            )
    return issues


def validate_diacritics_rows(
    rows: list[tuple[int, str, str]],
    *,
    use_diacritics: DiacriticsMode,
) -> list[DiacriticsIssue]:
    """Validate (line_no, filepath, text) rows against ``use_diacritics`` expectation."""
    if use_diacritics == "mixed":
        return validate_mixed_diacritics_rows(rows)

    issues: list[DiacriticsIssue] = []
    arabic_row_count = 0

    for line_no, filepath, text in rows:
        if contains_arabic_script(text):
            arabic_row_count += 1
        issue = _check_row(line_no, filepath, text, use_diacritics=bool(use_diacritics))
        if issue is not None:
            issues.append(issue)

    if use_diacritics and arabic_row_count == 0:
        issues.insert(
            0,
            DiacriticsIssue(
                line_no=0,
                filepath="",
                text="",
                reason="no Arabic script found in filelist (use_diacritics=true)",
            ),
        )

    return issues
