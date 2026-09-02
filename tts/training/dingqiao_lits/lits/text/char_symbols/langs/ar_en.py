"""
Mixed Arabic-English Symbol Set: Arabic characters + English ARPAbet tokens.

Arabic side keeps raw orthographic characters (+ optional diacritics).
English side uses ARPAbet phoneme tokens (e.g. AA0, DH, EY1 …).
This replaces the earlier IPA-based symbol set.
"""
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from lits.text.char_symbols.langs.ARPA import ARPA_TOKENS

_pad = "<blank>"
_eos = "<eos>"
_unknown = "<unk>"
_word_boundary = "_"
_special_symbols = [_pad, _eos, _unknown, _word_boundary]

_arabic_letters = "ءآأؤإئابةتثجحخدذرزسشصضطظعغفقكلمنهويى"

_arabic_diacritics = ['َ', 'ً', 'ُ', 'ٌ', 'ِ', 'ٍ', 'ْ', 'ّ', 'ٔ', 'ٓ', 'ٰ']

_arpabet_tokens = ARPA_TOKENS

_punctuation = [
    "،", "؛", "؟",  # arabic
    ";", ":", ",", ".", "!", "?", "¡", "¿", "—", "…", "'", "\"", "«", "»", "“", "”", " ",
    "/", "-", "٪", "×", "÷", "+", "=", "*", "%", "^", "°", "’", "–",
    "(", ")"]

# --- Build final symbol list ---
symbols = (
    _special_symbols
    + list(_arabic_letters)
    + _arabic_diacritics
    + _arpabet_tokens
    + _punctuation
)

symbols = list(dict.fromkeys(symbols))

PAD_ID = symbols.index(_pad)
EOS_ID = symbols.index(_eos)
UNK_ID = symbols.index(_unknown)
WORD_SEP_ID = symbols.index(_word_boundary)

assert [PAD_ID, EOS_ID, UNK_ID, WORD_SEP_ID] == [0, 1, 2, 3], (
    f"Expected [0,1,2,3], got {[PAD_ID, EOS_ID, UNK_ID, WORD_SEP_ID]}"
)

if __name__ == "__main__":
    id2symbol = {idx: s for idx, s in enumerate(symbols)}
    symbol2id = {s: idx for idx, s in enumerate(symbols)}
    print(f"AR-EN (Arabic char + English ARPA) 符号集总数: {len(symbols)}")
    print(symbol2id)
