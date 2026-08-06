"""CMUdict + optional supplement lexicon G2P engine."""

from __future__ import annotations

import json
import re
from pathlib import Path

from cmudict_loader import CMUDict, DEFAULT_CMUDICT_PATH

_PKG_ROOT = Path(__file__).resolve().parent
DEFAULT_SUPPLEMENT_PATH = _PKG_ROOT / "data" / "supplement_lexicon.json"

_ENGLISH_TOKEN_RE = re.compile(
    r"[A-Za-z]+(?:['''-][A-Za-z]+)*|"
    r"\.\.\.|"
    r"[,.\?!;:\"'()—\-]"
)


class SupplementLexicon:
    def __init__(self, entries: dict[str, list[str]]) -> None:
        self._entries = {k.upper(): v for k, v in entries.items()}

    @classmethod
    def from_json(cls, path: str | Path) -> SupplementLexicon:
        path = Path(path)
        if not path.is_file():
            return cls({})
        data = json.loads(path.read_text(encoding="utf-8"))
        raw_entries = data.get("entries", data)
        parsed: dict[str, list[str]] = {}
        for key, value in raw_entries.items():
            if isinstance(value, dict) and "phones" in value:
                parsed[key] = list(value["phones"])
            elif isinstance(value, list):
                parsed[key] = list(value)
            elif isinstance(value, str):
                parsed[key] = value.split()
        return cls(parsed)

    def lookup(self, word: str) -> list[str] | None:
        phones = self._entries.get(word.strip().upper())
        if phones is None:
            return None
        return list(phones)

    def __len__(self) -> int:
        return len(self._entries)


class CMUDictG2P:
    def __init__(
        self,
        cmudict: CMUDict,
        supplement: SupplementLexicon | None = None,
    ) -> None:
        self.cmudict = cmudict
        self.supplement = supplement or SupplementLexicon({})

    @classmethod
    def from_paths(
        cls,
        cmudict_path: str | Path = DEFAULT_CMUDICT_PATH,
        supplement_path: str | Path = DEFAULT_SUPPLEMENT_PATH,
    ) -> CMUDictG2P:
        return cls(
            CMUDict.from_file(cmudict_path),
            SupplementLexicon.from_json(supplement_path),
        )

    def lookup_word_phonemes_with_fallback(self, word: str) -> tuple[list[str], str]:
        phones = self.cmudict.lookup_word(word)
        if phones is not None:
            return phones, "cmudict"

        phones = self.supplement.lookup(word)
        if phones is not None:
            return phones, "supplement"

        spelled = self._spell_word(word)
        if spelled:
            return spelled, "spell"
        return [], "missing"

    def lookup_isolated_letter_phonemes(
        self,
        letter: str,
        *,
        prefer_letter_name: bool = False,
    ) -> tuple[list[str], str]:
        """Letter-name or article reading for an isolated A–Z token.

        CMUdict's primary ``A`` is the indefinite article (AH0); ``A(1)`` is the
        letter name (EY1). Use ``prefer_letter_name=True`` for plate-style
        isolated letters in mixed zh-en text; English ``A dog`` keeps AH0.
        """
        if len(letter) != 1 or not letter.isalpha():
            return [], "missing"

        variants = self.cmudict.lookup_variants(letter)
        if variants:
            if letter.upper() == "A" and prefer_letter_name and len(variants) > 1:
                return list(variants[1]), "cmudict"
            return list(variants[0]), "cmudict"

        phones = self.supplement.lookup(letter)
        if phones:
            return list(phones), "supplement"
        return [], "missing"

    def _spell_word(self, word: str) -> list[str]:
        letters = [ch for ch in word.upper() if ch.isalpha()]
        if not letters:
            return []
        phones: list[str] = []
        for letter in letters:
            letter_phones = self.cmudict.lookup_word(letter)
            if letter_phones is None:
                return []
            phones.extend(letter_phones)
        return phones

    def _lookup_hyphenated(self, word: str) -> list[str] | None:
        if "-" not in word:
            return None
        parts = [part for part in word.split("-") if part]
        if len(parts) < 2:
            return None
        combined: list[str] = []
        for part in parts:
            phones, source = self.lookup_word_phonemes_with_fallback(part)
            if source == "missing":
                return None
            combined.extend(phones)
        return combined

    def lookup_phrase_phonemes(self, word: str) -> tuple[list[str], str]:
        if "-" in word:
            hyphenated = self._lookup_hyphenated(word)
            if hyphenated:
                return hyphenated, "hyphen"

        direct, source = self.lookup_word_phonemes_with_fallback(word)
        if direct:
            if (
                source == "supplement"
                and "-" in word
                and len(direct) < max(3, len(word.replace("-", "")) // 3)
            ):
                hyphenated = self._lookup_hyphenated(word)
                if hyphenated:
                    return hyphenated, "hyphen"
            return direct, source

        return [], "missing"


def _collapse_dash_runs(tokens: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(tokens):
        kind, surface = tokens[i]
        if (
            kind == "punct"
            and surface == "-"
            and i + 1 < len(tokens)
            and tokens[i + 1] == ("punct", "-")
            and out
            and out[-1][0] == "word"
            and i + 2 < len(tokens)
            and tokens[i + 2][0] == "word"
        ):
            out.append(("punct", "—"))
            i += 2
            continue
        out.append((kind, surface))
        i += 1
    return out


def tokenize_english_text(text: str) -> list[tuple[str, str]]:
    """Tokenize English text into ('word'|'punct', surface) pairs."""
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        match = _ENGLISH_TOKEN_RE.match(text, i)
        if not match:
            i += 1
            continue
        surface = match.group()
        i = match.end()
        if re.fullmatch(r"[A-Za-z]+(?:[''-][A-Za-z]+)*", surface):
            tokens.append(("word", surface))
        else:
            tokens.append(("punct", surface))
    return _collapse_dash_runs(tokens)
