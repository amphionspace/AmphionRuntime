import re

from . import language_cleaners as cleaners
from .char_symbols.symbol_inventories import lang2inventory


class UnknownCleanerException(Exception):
    pass


_SYMBOLS_DB = lang2inventory

_CLEANER_TO_MODEL_KEY = {
    "pinyin_direct_mixed_cleaners": "zh-en-direct",
    "en_zh_dict_mixed_cleaners": "zh-en-direct",
    "english_direct_phoneme_cleaners": "en-g2p",
    "ar_en_mixed_cleaners": "ar-en",
    "ar_en_dict_mixed_cleaners": "ar-en",
    "bn_en_mixed_cleaners": "bn-en",
    "bn_en_dict_mixed_cleaners": "bn-en",
    "en_ru_mixed_cleaners": "en-ru",
    "en_ru_dict_mixed_cleaners": "en-ru",
}

_ACTIVE_MODEL_KEY = None
symbols = []
_symbol_to_id = {}
_id_to_symbol = {}
_BLANK_ID = 0
_TOKEN_SEQUENCE_CLEANERS = {
    "pinyin_direct_mixed_cleaners",
    "en_zh_dict_mixed_cleaners",
    "english_direct_phoneme_cleaners",
    "ar_en_mixed_cleaners",
    "ar_en_dict_mixed_cleaners",
    "bn_en_mixed_cleaners",
    "bn_en_dict_mixed_cleaners",
    "en_ru_mixed_cleaners",
    "en_ru_dict_mixed_cleaners",
}
_TOKEN_MODEL_KEYS = {
    "en-g2p",
    "zh-en-direct",
    "ar-en",
    "bn-en",
    "en-ru",
}


def _activate_model_symbols(model_key: str):
    global _ACTIVE_MODEL_KEY, symbols, _symbol_to_id, _id_to_symbol

    payload = _SYMBOLS_DB.get(model_key)
    if payload is None:
        raise ValueError(f"model_key '{model_key}' not found in symbol inventories")

    symbols_local = payload.get("symbols", [])
    if not symbols_local:
        raise ValueError(f"'symbols' for model_key '{model_key}' is empty")

    symbol_to_id = payload.get("symbol_to_id")
    if not symbol_to_id:
        symbol_to_id = {s: i for i, s in enumerate(symbols_local)}

    id_to_symbol = payload.get("id_to_symbol")
    if id_to_symbol:
        id_to_symbol = {int(k): v for k, v in id_to_symbol.items()}
    else:
        id_to_symbol = {i: s for s, i in symbol_to_id.items()}

    _ACTIVE_MODEL_KEY = model_key
    symbols = symbols_local
    _symbol_to_id = symbol_to_id
    _id_to_symbol = id_to_symbol


def _resolve_model_key(cleaner_names):
    for name in cleaner_names:
        if name in _CLEANER_TO_MODEL_KEY:
            return _CLEANER_TO_MODEL_KEY[name]
    return next(iter(_SYMBOLS_DB.keys()))


def _ensure_active_symbols():
    if not _symbol_to_id:
        _activate_model_symbols(next(iter(_SYMBOLS_DB.keys())))


def text_to_sequence(text, cleaner_names):
    model_key = _resolve_model_key(cleaner_names)
    if model_key != _ACTIVE_MODEL_KEY:
        _activate_model_symbols(model_key)

    clean_text = _clean_text(text, cleaner_names)

    sequence = []
    unk_id = _symbol_to_id.get("<unk>", _symbol_to_id.get(" ", 0))
    if any(name in _TOKEN_SEQUENCE_CLEANERS for name in cleaner_names):
        for token in clean_text.split():
            sequence.append(_symbol_to_id.get(token, unk_id))
    else:
        for symbol in clean_text:
            sequence.append(_symbol_to_id.get(symbol, unk_id))
    return sequence, clean_text


def _clean_text(text, cleaner_names):
    text = cleaners.preprocess_text(text)
    for name in cleaner_names:
        cleaner = getattr(cleaners, name, None)
        if not cleaner:
            raise UnknownCleanerException(f"Unknown cleaner: '{name}'")
        text = cleaner(text)
    return text


def sequence_to_text(sequence):
    _ensure_active_symbols()
    result = ""
    for symbol_id in sequence:
        if symbol_id != _BLANK_ID and symbol_id in _id_to_symbol:
            result += _id_to_symbol[symbol_id]
    return result


def ids_to_tokens(sequence):
    return sequence_to_text(sequence)


def cleaned_text_to_sequence(cleaned_text):
    _ensure_active_symbols()
    unk_id = _symbol_to_id.get("<unk>", 0)
    sequence = []
    for token in cleaned_text.split():
        sequence.append(_symbol_to_id.get(token, unk_id))
    return sequence
