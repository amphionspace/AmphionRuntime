"""
Mixed Bengali-English Symbol Set: Bengali characters + English ARPAbet tokens.

Bengali side keeps NFC-normalized orthographic characters.
NFC decomposes nukta precomposed forms (ড়/ঢ়/য়) into base + nukta (়),
so the symbol set only needs the base consonants + nukta as separate tokens.
English side uses ARPAbet phoneme tokens (same set as ar_en).
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

# Bengali vowels (12)
_bn_vowels = "অআইঈউঊঋএঐওঔ"

# Bengali consonants (33) — no precomposed nukta forms (ড়/ঢ়/য়)
_bn_consonants = "কখগঘঙচছজঝঞটঠডঢণতথদধনপফবভমযরলশষসহৎ"

# Bengali modifiers (4): anusvara, visarga, chandrabindu, nukta
_bn_modifiers = "ংঃঁ়"

# Bengali vowel signs (10) + hasanta (1)
_bn_diacritics = "ািীুূৃেৈোৌ্"

# Bengali digits (10)
_bn_digits = "০১২৩৪৫৬৭৮৯"

_bengali_chars = _bn_vowels + _bn_consonants + _bn_modifiers + _bn_diacritics + _bn_digits

_arpabet_tokens = ARPA_TOKENS

_punctuation = [
    "।", ";", ":", ",", ".", "!", "?", "¡", "¿", "—", "…", "'", "\"", "«", "»", "“", "”", " ",
    "/", "-", "٪", "×", "÷", "+", "=", "*", "%", "^", "°", "’", "–",
    "(", ")"]

# --- Build final symbol list ---
symbols = (
    _special_symbols
    + list(_bengali_chars)
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
    print(f"BN-EN (Bengali char + English ARPA) 符号集总数: {len(symbols)}")
    print(symbol2id)
