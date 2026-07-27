# Voiceprint fallback gate fixtures

This directory is the fixed two-file corpus for the Android and Harmony
`voiceprint-fallback` release gate.

| File | Purpose | Format | SHA-256 |
| --- | --- | --- | --- |
| `000_enroll.wav` | Voiceprint enrollment | PCM 16-bit mono, 16 kHz | `406027619ac5356b902338e50c7c4ec665e86de1c205835216dde89a3cda67bc` |
| `001_recognize.wav` | Recognition and utterance-PCM fallback | PCM 16-bit mono, 16 kHz | `3b8255aed49b90df4bdbd5ae626f37c94da318a4b2f3bd0c746ef2dbc8a7f8fc` |

Do not replace either file without updating the hashes, the release-gate
documentation, and the corresponding red/green device evidence.
