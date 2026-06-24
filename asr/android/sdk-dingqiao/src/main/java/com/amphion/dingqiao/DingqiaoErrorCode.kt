package com.amphion.dingqiao

/** 鼎桥接口错误码，与 [语音识别SDK接口.md] 对齐。 */
object DingqiaoErrorCode {
    const val CREATE_ENGINE_FAILED = 1002200001
    const val START_LISTENING_FAILED = 1002200002
    const val MAX_AUDIO_DURATION = 1002200003
    const val FINISH_FAILED = 1002200004
    const val CANCEL_FAILED = 1002200005
    const val ENGINE_BUSY = 1002200006
    const val ENGINE_NOT_INITIALIZED = 1002200007
    const val ENGINE_DESTROYED = 1002200008
    const val INTERNAL_ERROR = 1002200009
    const val NOT_LISTENING = 1002200010
    const val RECOGNITION_ERROR = 1002200011
    const val VOICEPRINT_REGISTER_FAILED = 1002200020
    const val VOICEPRINT_SAMPLE_COUNT = 1002200021
    const val VOICEPRINT_SAMPLE_DURATION = 1002200022
    const val VOICEPRINT_NOT_FOUND = 1002200024
    const val LICENSE_FILE_UNREADABLE = 1002200030
    const val LICENSE_INVALID = 1002200031
    const val LICENSE_EXPIRED = 1002200032
    const val LICENSE_DEVICE_MISMATCH = 1002200033
    const val LICENSE_NOT_SET = 1002200034
    const val LICENSE_ACTIVATION_FAILED = 1002200035
}

/** 运行模式：当前仅支持离线。 */
object DingqiaoOnlineMode {
    const val OFFLINE = 1
}

/** 识别模式：外部写入音频流。 */
object DingqiaoRecognitionMode {
    const val RECORD = 0
    const val STREAM = 1
}

/** VAD 事件码。 */
object DingqiaoEventCode {
    const val SPEECH_BEGIN = 1
    const val SPEECH_END = 3
    const val SPEAKER_VAD_CHANGED = 20
    const val SPEAKER_VAD_DEBUG = 21
    const val SPEAKER_VAD_REJECTED = 22
}

/** 声纹注册成功状态码。 */
object DingqiaoVoiceprintStatus {
    const val SUCCESS = 0
}

/** 默认声纹 ONNX 文件名，应置于 [SpeechRecognizeSdk.setWorkPath] 目录下。 */
const val DINGQIAO_SPEAKER_MODEL_FILENAME = "eres2net.onnx"

/** 写入音频帧字节数（16 kHz mono 16-bit PCM，20 ms）。 */
const val DINGQIAO_AUDIO_FRAME_BYTES = 640

/** 遗留 40 ms 帧大小常量。交付接口只接受 640 字节 / 20 ms 帧。 */
@Deprecated("Dingqiao delivery interface only accepts 640-byte / 20 ms frames.")
const val DINGQIAO_AUDIO_FRAME_BYTES_40MS = 1280

/** 声纹样本最短 / 最长时长（秒）。 */
const val DINGQIAO_VOICEPRINT_MIN_SEC = 3
const val DINGQIAO_VOICEPRINT_MAX_SEC = 8

/** 声纹样本数量范围。 */
const val DINGQIAO_VOICEPRINT_MIN_SAMPLES = 3
const val DINGQIAO_VOICEPRINT_MAX_SAMPLES = 5
