import Foundation

public let DINGQIAO_AUDIO_FRAME_BYTES_20MS = 640
public let DINGQIAO_AUDIO_FRAME_BYTES = DINGQIAO_AUDIO_FRAME_BYTES_20MS
public let DINGQIAO_VOICEPRINT_MIN_SAMPLES = 1
public let DINGQIAO_VOICEPRINT_MIN_SEC = 3
public let DINGQIAO_VOICEPRINT_MAX_SEC = 8

@available(*, deprecated, message: "The delivery API accepts 640-byte / 20 ms frames.")
public let DINGQIAO_AUDIO_FRAME_BYTES_40MS = 1280

public enum DingqiaoOnlineMode {
    public static let offline = 1
}

public enum DingqiaoRecognitionMode {
    public static let record = 0
    public static let stream = 1
    @available(*, deprecated, renamed: "record") public static let single = record
    @available(*, deprecated, renamed: "stream") public static let continuous = stream
}

public enum DingqiaoEventCode {
    public static let speechBegin = 1
    public static let speechEnd = 3
    public static let speakerVadChanged = 20
    public static let speakerVadDebug = 21
    public static let speakerVadRejected = 22
}

public enum DingqiaoErrorCode {
    public static let createEngineFailed = 1002200001
    public static let startListeningFailed = 1002200002
    public static let maxAudioDuration = 1002200003
    public static let finishFailed = 1002200004
    public static let cancelFailed = 1002200005
    public static let engineBusy = 1002200006
    public static let engineNotInitialized = 1002200007
    public static let engineDestroyed = 1002200008
    public static let internalError = 1002200009
    public static let notListening = 1002200010
    public static let recognitionError = 1002200011
    public static let noMicPermission = 1002200012
    public static let voiceprintRegisterFailed = 1002200020
    public static let voiceprintSampleCount = 1002200021
    public static let voiceprintSampleDuration = 1002200022
    public static let voiceprintNotFound = 1002200024
    public static let licenseFileUnreadable = 1002200030
    public static let licenseInvalid = 1002200031
    public static let licenseExpired = 1002200032
    public static let licenseDeviceMismatch = 1002200033
    public static let licenseNotSet = 1002200034
    public static let licenseActivationFailed = 1002200035
}

public struct DingqiaoAudioInfo {
    public var audioType: String
    public var sampleRate: Int
    public var sampleBit: Int
    public var soundChannel: Int

    public init(
        audioType: String = "pcm",
        sampleRate: Int = 16_000,
        sampleBit: Int = 16,
        soundChannel: Int = 1
    ) {
        self.audioType = audioType
        self.sampleRate = sampleRate
        self.sampleBit = sampleBit
        self.soundChannel = soundChannel
    }
}

public struct DingqiaoCreateEngineParams {
    public var language: String
    public var online: Int
    public var extraParams: [String: Any]

    public init(
        language: String = "zh-CN",
        online: Int = DingqiaoOnlineMode.offline,
        extraParams: [String: Any] = [:]
    ) {
        self.language = language
        self.online = online
        self.extraParams = extraParams
    }
}

public struct DingqiaoSpeakerDiarizationConfig {
    public var maxSpeakers: Int
    public init(maxSpeakers: Int = 4) { self.maxSpeakers = maxSpeakers }
}

public struct DingqiaoStartParams {
    public var sessionId: String
    public var audioInfo: DingqiaoAudioInfo
    public var extraParams: [String: Any]
    public var speakerDiarization: DingqiaoSpeakerDiarizationConfig?

    public init(
        sessionId: String = "",
        audioInfo: DingqiaoAudioInfo = DingqiaoAudioInfo(),
        extraParams: [String: Any] = [:],
        speakerDiarization: DingqiaoSpeakerDiarizationConfig? = nil
    ) {
        self.sessionId = sessionId
        self.audioInfo = audioInfo
        self.extraParams = extraParams
        self.speakerDiarization = speakerDiarization
    }
}

public struct DingqiaoSpeechRecognitionResult {
    public let isFinal: Bool
    public let isLast: Bool
    public let result: String
    public let beginTime: Int?
    public let endTime: Int?
    public let speakerSimilarity: Float?
    public let targetSpeakerEnhancementApplied: Bool?
    public let utteranceId: String?
    public let speakerIndex: Int
    public let secondarySpeakerIndexes: [Int]
    public let speakerConfidence: Float

    public init(
        isFinal: Bool = false,
        isLast: Bool = false,
        result: String = "",
        beginTime: Int? = nil,
        endTime: Int? = nil,
        speakerSimilarity: Float? = nil,
        targetSpeakerEnhancementApplied: Bool? = nil,
        utteranceId: String? = nil,
        speakerIndex: Int = -1,
        secondarySpeakerIndexes: [Int] = [],
        speakerConfidence: Float = 0
    ) {
        self.isFinal = isFinal
        self.isLast = isLast
        self.result = result
        self.beginTime = beginTime
        self.endTime = endTime
        self.speakerSimilarity = speakerSimilarity
        self.targetSpeakerEnhancementApplied = targetSpeakerEnhancementApplied
        self.utteranceId = utteranceId
        self.speakerIndex = speakerIndex
        self.secondarySpeakerIndexes = secondarySpeakerIndexes
        self.speakerConfidence = speakerConfidence
    }
}

/// Explicit preflight snapshot for parameters that exist on Android, HarmonyOS and iOS.
/// A false value means the current iOS delivery must not advertise that capability.
public struct DingqiaoRuntimeCapabilities: Equatable {
    public let voiceprint: Bool
    public let speakerVad: Bool
    public let speakerDiarization: Bool
    public let inverseTextNormalization: Bool
    public let punctuation: Bool
    public let policeEnhancement: Bool
    public let formalOfflineLicense: Bool
    public let diagnosticSchemaV2: Bool

    public init(voiceprint: Bool = false, speakerVad: Bool = false,
                speakerDiarization: Bool = false, inverseTextNormalization: Bool = false,
                punctuation: Bool = false, policeEnhancement: Bool = false,
                formalOfflineLicense: Bool = false, diagnosticSchemaV2: Bool = false) {
        self.voiceprint = voiceprint
        self.speakerVad = speakerVad
        self.speakerDiarization = speakerDiarization
        self.inverseTextNormalization = inverseTextNormalization
        self.punctuation = punctuation
        self.policeEnhancement = policeEnhancement
        self.formalOfflineLicense = formalOfflineLicense
        self.diagnosticSchemaV2 = diagnosticSchemaV2
    }
}

public struct DingqiaoSpeakerDiarizationUpdate {
    public let utteranceId: String
    public let revision: Int
    public let speakerIndex: Int
    public let secondarySpeakerIndexes: [Int]
    public let beginTime: Int
    public let endTime: Int
    public let confidence: Float

    public init(utteranceId: String = "", revision: Int = 0, speakerIndex: Int = -1,
                secondarySpeakerIndexes: [Int] = [], beginTime: Int = 0, endTime: Int = 0,
                confidence: Float = 0) {
        self.utteranceId = utteranceId; self.revision = revision; self.speakerIndex = speakerIndex
        self.secondarySpeakerIndexes = secondarySpeakerIndexes; self.beginTime = beginTime
        self.endTime = endTime; self.confidence = confidence
    }
}

public struct DingqiaoDiarizedUtterance {
    public let utteranceId: String; public let rawText: String; public let text: String
    public let beginTime: Int; public let endTime: Int; public let speakerIndex: Int
    public let secondarySpeakerIndexes: [Int]; public let confidence: Float; public let overlap: Bool
    public init(utteranceId: String = "", rawText: String = "", text: String = "",
                beginTime: Int = 0, endTime: Int = 0, speakerIndex: Int = -1,
                secondarySpeakerIndexes: [Int] = [], confidence: Float = 0, overlap: Bool = false) {
        self.utteranceId = utteranceId; self.rawText = rawText; self.text = text
        self.beginTime = beginTime; self.endTime = endTime; self.speakerIndex = speakerIndex
        self.secondarySpeakerIndexes = secondarySpeakerIndexes; self.confidence = confidence
        self.overlap = overlap
    }
}

public struct DingqiaoSpeakerTurn {
    public let beginTime: Int; public let endTime: Int; public let speakerIndex: Int
    public let secondarySpeakerIndexes: [Int]; public let confidence: Float; public let overlap: Bool
    public init(beginTime: Int = 0, endTime: Int = 0, speakerIndex: Int = -1,
                secondarySpeakerIndexes: [Int] = [], confidence: Float = 0, overlap: Bool = false) {
        self.beginTime = beginTime; self.endTime = endTime; self.speakerIndex = speakerIndex
        self.secondarySpeakerIndexes = secondarySpeakerIndexes; self.confidence = confidence
        self.overlap = overlap
    }
}

public enum DingqiaoSpeakerDiarizationDegradedReason: String {
    case none = "NONE", inferenceUnavailable = "INFERENCE_UNAVAILABLE"
    case modelUnavailable = "MODEL_UNAVAILABLE", inferenceTimeout = "INFERENCE_TIMEOUT"
    case finishTimeout = "FINISH_TIMEOUT", storageUnavailable = "STORAGE_UNAVAILABLE"
    case speakerLimitExceeded = "SPEAKER_LIMIT_EXCEEDED"
}

public struct DingqiaoSpeakerDiarizationResult {
    public let utterances: [DingqiaoDiarizedUtterance]; public let speakerTurns: [DingqiaoSpeakerTurn]
    public let speakerCount: Int; public let degraded: Bool
    public let degradedReason: DingqiaoSpeakerDiarizationDegradedReason; public let degradedMessage: String?
    public let inferenceMs: Int64; public let rtf: Float
    public init(utterances: [DingqiaoDiarizedUtterance] = [], speakerTurns: [DingqiaoSpeakerTurn] = [],
                speakerCount: Int = 0, degraded: Bool = false,
                degradedReason: DingqiaoSpeakerDiarizationDegradedReason = .none,
                degradedMessage: String? = nil, inferenceMs: Int64 = 0, rtf: Float = 0) {
        self.utterances = utterances; self.speakerTurns = speakerTurns; self.speakerCount = speakerCount
        self.degraded = degraded; self.degradedReason = degradedReason
        self.degradedMessage = degradedMessage; self.inferenceMs = inferenceMs; self.rtf = rtf
    }
}

public struct DingqiaoVoiceprintRegisterParams {
    public var samplePaths: [String]; public var audioInfo: DingqiaoAudioInfo; public var voiceprintId: String
    public init(samplePaths: [String] = [], audioInfo: DingqiaoAudioInfo = DingqiaoAudioInfo(),
                voiceprintId: String = "") {
        self.samplePaths = samplePaths; self.audioInfo = audioInfo; self.voiceprintId = voiceprintId
    }
}

public struct DingqiaoVoiceprintRegisterResult {
    public let voiceprintId: [String: String]; public let status: Int; public let message: String
    public init(voiceprintId: [String: String] = [:], status: Int = 0, message: String = "") {
        self.voiceprintId = voiceprintId; self.status = status; self.message = message
    }
}

public struct DingqiaoLicenseInfo {
    public let status: Int; public let expireTime: Int64; public let remainingDays: Int
    public let authorizedFeatures: [String]
    public init(status: Int = 0, expireTime: Int64 = -1, remainingDays: Int = -1,
                authorizedFeatures: [String] = []) {
        self.status = status; self.expireTime = expireTime; self.remainingDays = remainingDays
        self.authorizedFeatures = authorizedFeatures
    }
}

public struct DingqiaoLicenseActivationResult {
    public let errorCode: Int; public let errorMessage: String; public let remainingDays: Int?
    public let authorizedFeatures: [String]?
    public init(errorCode: Int = 0, errorMessage: String = "", remainingDays: Int? = nil,
                authorizedFeatures: [String]? = nil) {
        self.errorCode = errorCode; self.errorMessage = errorMessage; self.remainingDays = remainingDays
        self.authorizedFeatures = authorizedFeatures
    }
}

public enum DingqiaoDiagnosticMode {
    public static let BASIC = "BASIC"
    public static let CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    public static let FAILURE_ONLY = "FAILURE_ONLY"
}

public struct DingqiaoDiagnosticOptions {
    public var enabled: Bool; public var mode: String; public var captureAudio: Bool
    public var includeRecognitionText: Bool; public var maxSessionAudioSec: Int
    public var failureRingAudioSec: Int; public var maxSessionEvents: Int
    public var maxDirectoryMb: Int; public var maxRetainedRuns: Int
    public init(enabled: Bool = false, mode: String = DingqiaoDiagnosticMode.BASIC,
                captureAudio: Bool = false, includeRecognitionText: Bool = false,
                maxSessionAudioSec: Int = 300, failureRingAudioSec: Int = 20,
                maxSessionEvents: Int = 512, maxDirectoryMb: Int = 200,
                maxRetainedRuns: Int = 3) {
        self.enabled = enabled; self.mode = mode; self.captureAudio = captureAudio
        self.includeRecognitionText = includeRecognitionText
        self.maxSessionAudioSec = maxSessionAudioSec; self.failureRingAudioSec = failureRingAudioSec
        self.maxSessionEvents = maxSessionEvents; self.maxDirectoryMb = maxDirectoryMb
        self.maxRetainedRuns = maxRetainedRuns
    }
    public static func customerSupport() -> Self { .init(enabled: true, mode: DingqiaoDiagnosticMode.CUSTOMER_SUPPORT) }
    public static func failureOnly() -> Self { .init(enabled: true, mode: DingqiaoDiagnosticMode.FAILURE_ONLY) }
}

public protocol DingqiaoDiagnosticExportCallback: AnyObject {
    func onSuccess(path: String)
    func onError(errorCode: Int, errorMessage: String)
}

public protocol DingqiaoRecognitionListener: AnyObject {
    func onStart(sessionId: String, eventMessage: String)
    func onEvent(sessionId: String, eventCode: Int, eventMessage: String)
    func onResult(sessionId: String, result: DingqiaoSpeechRecognitionResult)
    func onSpeakerDiarizationUpdate(sessionId: String, update: DingqiaoSpeakerDiarizationUpdate)
    func onSpeakerDiarizationResult(sessionId: String, result: DingqiaoSpeakerDiarizationResult)
    func onComplete(sessionId: String, eventMessage: String)
    func onError(sessionId: String, errorCode: Int, errorMessage: String)
}

public extension DingqiaoRecognitionListener {
    func onStart(sessionId: String, eventMessage: String) {}
    func onEvent(sessionId: String, eventCode: Int, eventMessage: String) {}
    func onResult(sessionId: String, result: DingqiaoSpeechRecognitionResult) {}
    func onSpeakerDiarizationUpdate(sessionId: String, update: DingqiaoSpeakerDiarizationUpdate) {}
    func onSpeakerDiarizationResult(sessionId: String, result: DingqiaoSpeakerDiarizationResult) {}
    func onComplete(sessionId: String, eventMessage: String) {}
    func onError(sessionId: String, errorCode: Int, errorMessage: String) {}
}

public protocol DingqiaoSpeechRecognitionEngine: AnyObject {
    func setListener(_ listener: DingqiaoRecognitionListener?)
    func startListening(_ params: DingqiaoStartParams)
    func writeAudio(sessionId: String, audio: Data)
    func finish(sessionId: String)
    func cancel(sessionId: String)
    func setSpeakerVadEnabled(_ enabled: Bool)
    func isBusy() -> Bool
    func shutdown()
}

public protocol DingqiaoCreateEngineCallback: AnyObject {
    func onSuccess(engine: DingqiaoSpeechRecognitionEngine)
    func onError(errorCode: Int, errorMessage: String)
}

public protocol DingqiaoPrepareRuntimeCallback: AnyObject {
    func onReady()
    func onError(errorCode: Int, errorMessage: String)
}

public protocol DingqiaoVoiceprintRegisterCallback: AnyObject {
    func onResult(result: DingqiaoVoiceprintRegisterResult)
    func onError(errorCode: Int, errorMessage: String)
}
public extension DingqiaoVoiceprintRegisterCallback { func onError(errorCode: Int, errorMessage: String) {} }

public protocol DingqiaoLicenseActivationCallback: AnyObject {
    func onResult(result: DingqiaoLicenseActivationResult)
    func onError(errorCode: Int, errorMessage: String)
}
public extension DingqiaoLicenseActivationCallback { func onError(errorCode: Int, errorMessage: String) {} }

// Customer-facing names follow the Android/Harmony Dingqiao documents. The prefixed concrete
// names remain available to avoid collisions in applications that already define generic types.
public typealias AudioInfo = DingqiaoAudioInfo
public typealias CreateEngineParams = DingqiaoCreateEngineParams
public typealias StartParams = DingqiaoStartParams
public typealias SpeakerDiarizationConfig = DingqiaoSpeakerDiarizationConfig
public typealias SpeechRecognitionResult = DingqiaoSpeechRecognitionResult
public typealias SpeakerDiarizationUpdate = DingqiaoSpeakerDiarizationUpdate
public typealias DiarizedUtterance = DingqiaoDiarizedUtterance
public typealias SpeakerTurn = DingqiaoSpeakerTurn
public typealias SpeakerDiarizationDegradedReason = DingqiaoSpeakerDiarizationDegradedReason
public typealias SpeakerDiarizationResult = DingqiaoSpeakerDiarizationResult
public typealias VoiceprintRegisterParams = DingqiaoVoiceprintRegisterParams
public typealias VoiceprintRegisterResult = DingqiaoVoiceprintRegisterResult
public typealias LicenseInfo = DingqiaoLicenseInfo
public typealias LicenseActivationResult = DingqiaoLicenseActivationResult
@available(*, deprecated, message: "Diagnostics behavior is selected by the SDK build variant.")
public typealias DiagnosticMode = DingqiaoDiagnosticMode
@available(*, deprecated, message: "Use the dedicated diagnostics artifact.")
public typealias DiagnosticOptions = DingqiaoDiagnosticOptions
public typealias DiagnosticExportCallback = DingqiaoDiagnosticExportCallback
public typealias RecognitionListener = DingqiaoRecognitionListener
public typealias SpeechRecognitionEngine = DingqiaoSpeechRecognitionEngine
public typealias CreateEngineCallback = DingqiaoCreateEngineCallback
public typealias PrepareRuntimeCallback = DingqiaoPrepareRuntimeCallback
public typealias VoiceprintRegisterCallback = DingqiaoVoiceprintRegisterCallback
public typealias LicenseActivationCallback = DingqiaoLicenseActivationCallback
