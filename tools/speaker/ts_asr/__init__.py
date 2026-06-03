"""TS-ASR 调研期工具包。

仅作为调研脚本（00..05）的内部依赖，不打进任何 SDK，不参与发布。

公开符号见 core.py 与 metrics.py。
"""

from .core import (  # noqa: F401
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_HOP_SEC,
    DEFAULT_WIN_SEC,
    DEFAULT_MIN_SEG_SEC,
    asr_decode_full_segment,
    build_recognizer,
    build_speaker,
    cosine,
    enroll,
    load_audio_mono16k,
    segment_score,
)
from .metrics import (  # noqa: F401
    binary_metrics,
    eer_threshold,
    sweep_threshold,
)
from .dataset import (  # noqa: F401
    DEFAULT_AUDIO_ROOT_LOCAL,
    DEFAULT_AUDIO_ROOT_REMOTE,
    EvalSample,
    TsHwTestDataset,
)
