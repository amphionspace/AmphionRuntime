# 173-token Chinese/English frontend

`zh_en_symbols.json` is an ordered embedding vocabulary: array index is token ID.
Do not sort it. The 173 entries include punctuation, tone marks and special tokens;
they are not 173 distinct phonemes. `<blank>`, `<sil>`, `<unk>` and `_` occupy IDs
0–3. Chinese syllables use an initial, a complete rhyme and a tone. For example,
光 (`guang1`) maps to `ㄍ ㄨㄤ ˉ`. English keeps the training ARPAbet inventory.

`pinyin_to_tokens.json` contains 3,003 entries, derived from the original pinyin
mapping with the training source's `split_bpmf_body` function. These files match
LITs-distill revision `d878405d1a2c10eef0aefe5eb3227ca1fd3de2eb` and the Student
10000 model used for the Android integration. The exporter checks the actual
supplied training symbols and converted mapping against these committed files.
Android resource staging rejects a declared 173-token bundle with different data.

The SHA256 of the symbol strings joined by LF, without a trailing LF, is
`28d699a37750b24e1cb241639047df9c436e1a6917beb2706ec81bf453089e5c`.
The JVM tests pin that order and validate pinyin references. Model weights and
customer licenses remain separate delivery files.
