"""
Mixed Russian-English Symbol Set
"""
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from lits.text.char_symbols.langs.ARPA import ARPA_TOKENS

# 1. 基础与特殊控制符号
_pad = "<blank>"
_eos = "<eos>"
_unknown = "<unk>"
_word_boundary = "_"
_special_symbols = [_pad, _eos, _unknown, _word_boundary]

# 2. 核心字母表
# 俄语字母 (包含大小写 33*2 = 66个)
_russian_letters = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"
# 针对俄语补充的额外符号（如软音标记或重音辅助符号）
_extra_symbols = ['́', '̀'] # 结合重音符号 (Combining Accent Marks)
_russian_chars = list(_russian_letters) + _extra_symbols

# 3. Arpa
_arpabet_tokens = ARPA_TOKENS

# 4. 标点符号 (整合俄语、英语及通用标点)
# 结构性引号/括号/破折号在 cleaner 中去除，此处仅保留句读及运算符号。
_punctuation = [
    ";", ":", ",", ".", "!", "?", "¡", "¿", "…", " ",
    "/", "٪", "×", "÷", "+", "=", "*", "%", "^", "°",
]


# --- 构建最终符号表 ---
symbols = (
    list(_special_symbols) +
    list(_russian_chars) +
    list(_arpabet_tokens) +
    list(_punctuation)
)

# 核心步骤：去重并保持顺序 (Ordered Set)
symbols = list(dict.fromkeys(symbols))

# ID 映射
PAD_ID = symbols.index(_pad)
EOS_ID = symbols.index(_eos)
UNK_ID = symbols.index(_unknown)
WORD_SEP_ID = symbols.index(_word_boundary)

assert [PAD_ID, EOS_ID, UNK_ID, WORD_SEP_ID] == [0, 1, 2, 3], (
    f"Expected [0,1,2,3], got {[PAD_ID, EOS_ID, UNK_ID, WORD_SEP_ID]}"
)

id2symbol = {idx: symb for idx, symb in enumerate(symbols)}
symbol2id = {symb: idx for idx, symb in enumerate(symbols)}

if __name__ == "__main__":
    print(f"俄英混合模型符号集总数: {len(symbols)}.") # 174