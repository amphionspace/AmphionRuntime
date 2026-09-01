import Foundation

internal enum DingqiaoParameterError: Error, Equatable, CustomStringConvertible {
    case invalid(String)
    case unsupported(String)

    var description: String {
        switch self {
        case .invalid(let message): return message
        case .unsupported(let message): return message
        }
    }
}

internal struct DingqiaoSessionOptions: Equatable {
    let recognizerMode: String
    let vadBeginMs: Int?
    let vadEndMs: Int
    let maxAudioDurationMs: Int64
    let endpointMaxUtteranceMs: Int
    let enablePartialResult: Bool
    let enablePoliceEnhancement: Bool
    let enableVoiceprintVerification: Bool
    let enableSpeakerVad: Bool
    let voiceprintIds: [String]
    let speakerVadThreshold: Float
    let speakerVadWindowMs: Int
    let speakerVadHopMs: Int
    let speakerVadConsecutiveBelow: Int
    let speakerDiarizationMaxSpeakers: Int?
}

internal enum DingqiaoParameterPolicy {
    private static let sessionPattern = try! NSRegularExpression(pattern: "^[A-Za-z0-9_-]+$")
    // Keep every public contract key visible in this platform implementation. Some phase-1 keys
    // are explicit capability gates rather than silently accepted no-ops.
    private static let contractKeys = [
        "locate", "recognizerMode", "sysGeneralLexicon", "disablePrepack",
        "recognitionMode", "vadBegin", "vadEnd", "enablePartialResult",
        "enablePoliceEnhancement", "maxAudioDuration", "enableContinuousRecognition",
        "endpointMaxUtteranceMs", "sessionGeneralLexicon", "enableVoiceprintVerification",
        "enableSpeakerVad", "voiceprintIds", "speakerVadThreshold", "speakerVadWindowMs",
        "speakerVadHopMs", "speakerVadConsecutiveBelow",
    ]

    static func validateCreate(_ params: DingqiaoCreateEngineParams) throws {
        _ = contractKeys
        guard params.online == DingqiaoOnlineMode.offline else {
            throw DingqiaoParameterError.invalid("only online=1 (offline recognition) is supported")
        }
        switch params.language.lowercased() {
        case "zh-cn", "zh-en", "zh_en": break
        default: throw DingqiaoParameterError.invalid("unsupported language: \(params.language)")
        }
        if let raw = params.extraParams["recognizerMode"] {
            _ = try recognizerMode(raw: raw)
        }
    }

    static func systemGeneralLexicon(_ params: DingqiaoCreateEngineParams) -> [String] {
        stringList(params.extraParams["sysGeneralLexicon"])
    }

    static func disablePrepack(_ params: DingqiaoCreateEngineParams) -> Bool {
        compatibleBool(params.extraParams["disablePrepack"], defaultValue: true)
    }

    static func parse(
        create: DingqiaoCreateEngineParams,
        start: DingqiaoStartParams
    ) throws -> DingqiaoSessionOptions {
        try validateCreate(create)
        try validateStartShape(start)

        if let config = start.speakerDiarization, !(1...4).contains(config.maxSpeakers) {
            throw DingqiaoParameterError.invalid("SpeakerDiarizationConfig.maxSpeakers must be in [1, 4]")
        }

        let continuous = strictBool(start.extraParams["enableContinuousRecognition"]) == true
        let modeRaw = start.extraParams["recognizerMode"] ?? create.extraParams["recognizerMode"]
        let mode: String
        if let modeRaw {
            mode = try recognizerMode(raw: modeRaw)
        } else {
            mode = continuous ? "long" : "short"
        }
        let endpointMs = positiveFinite(start.extraParams["endpointMaxUtteranceMs"])
            .map { max(1, Int($0.rounded())) } ?? 20_000

        let maxDuration: Int64
        if continuous {
            maxDuration = 0
        } else if let value = finiteDouble(start.extraParams["maxAudioDuration"]), value > 0 {
            maxDuration = Int64(min(value, 28_800_000).rounded()).clampedToAtLeastOne
        } else {
            maxDuration = 0
        }

        return DingqiaoSessionOptions(
            recognizerMode: mode,
            vadBeginMs: clampedRounded(start.extraParams["vadBegin"], min: 500, max: 10_000),
            vadEndMs: clampedRounded(start.extraParams["vadEnd"], min: 500, max: 10_000) ?? 800,
            maxAudioDurationMs: maxDuration,
            endpointMaxUtteranceMs: endpointMs,
            enablePartialResult: strictBool(start.extraParams["enablePartialResult"]) ?? true,
            enablePoliceEnhancement: strictBool(start.extraParams["enablePoliceEnhancement"]) ?? true,
            enableVoiceprintVerification: strictBool(start.extraParams["enableVoiceprintVerification"]) ?? false,
            enableSpeakerVad: strictBool(start.extraParams["enableSpeakerVad"]) ?? false,
            voiceprintIds: stringList(start.extraParams["voiceprintIds"]),
            speakerVadThreshold: Float(clampedRoundedDouble(
                start.extraParams["speakerVadThreshold"], min: -1, max: 1) ?? 0.35),
            speakerVadWindowMs: clampedRounded(start.extraParams["speakerVadWindowMs"],
                                               min: 500, max: 5_000) ?? 1_500,
            speakerVadHopMs: clampedRounded(start.extraParams["speakerVadHopMs"],
                                            min: 100, max: 2_000) ?? 500,
            speakerVadConsecutiveBelow: clampedRounded(start.extraParams["speakerVadConsecutiveBelow"],
                                                       min: 1, max: 5) ?? 2,
            speakerDiarizationMaxSpeakers: start.speakerDiarization?.maxSpeakers
        )
    }

    static func validateRuntimeCapabilities(
        _ options: DingqiaoSessionOptions,
        policeEnhancementAvailable: Bool
    ) throws {
        if options.enablePoliceEnhancement && !policeEnhancementAvailable {
            throw DingqiaoParameterError.unsupported(
                "Police enhancement is unavailable in this iOS delivery; " +
                "set enablePoliceEnhancement=false or install an aligned Police runtime"
            )
        }
    }

    private static func validateStartShape(_ params: DingqiaoStartParams) throws {
        let range = NSRange(location: 0, length: params.sessionId.utf16.count)
        guard !params.sessionId.isEmpty,
              sessionPattern.firstMatch(in: params.sessionId, range: range) != nil else {
            throw DingqiaoParameterError.invalid("sessionId must match ^[A-Za-z0-9_-]+$")
        }
        let audio = params.audioInfo
        guard audio.audioType == "pcm", audio.sampleRate == 16_000,
              audio.sampleBit == 16, audio.soundChannel == 1 else {
            throw DingqiaoParameterError.invalid("audio must be PCM 16 kHz / 16 bit / mono")
        }
        let recognitionMode = finiteDouble(params.extraParams["recognitionMode"] ?? DingqiaoRecognitionMode.stream)
        guard recognitionMode == Double(DingqiaoRecognitionMode.stream) else {
            throw DingqiaoParameterError.invalid("only recognitionMode=1 (external audio stream) is supported")
        }
    }

    private static func recognizerMode(raw: Any) throws -> String {
        let mode = String(describing: raw).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard mode == "short" || mode == "long" else {
            throw DingqiaoParameterError.invalid("recognizerMode must be short or long")
        }
        return mode
    }

    private static func strictBool(_ raw: Any?) -> Bool? {
        raw as? Bool
    }

    private static func compatibleBool(_ raw: Any?, defaultValue: Bool) -> Bool {
        switch raw {
        case let value as Bool:
            return value
        case let value as NSNumber:
            let number = value.doubleValue
            return number.isFinite ? number != 0 : defaultValue
        case let value as String:
            let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            return normalized == "true" || normalized == "1"
        default:
            return defaultValue
        }
    }

    private static func positiveFinite(_ raw: Any?) -> Double? {
        guard let value = finiteDouble(raw), value > 0 else { return nil }
        return value
    }

    private static func clampedRounded(_ raw: Any?, min: Double, max: Double) -> Int? {
        guard let value = finiteDouble(raw) else { return nil }
        return Int(Swift.min(Swift.max(value, min), max).rounded())
    }

    private static func clampedRoundedDouble(_ raw: Any?, min: Double, max: Double) -> Double? {
        guard let value = finiteDouble(raw) else { return nil }
        return Swift.min(Swift.max(value, min), max)
    }

    private static func finiteDouble(_ raw: Any?) -> Double? {
        let value: Double?
        switch raw {
        case nil: value = nil
        case is Bool: value = nil
        case let number as NSNumber: value = number.doubleValue
        case let string as String: value = Double(string.trimmingCharacters(in: .whitespacesAndNewlines))
        default: value = nil
        }
        return value?.isFinite == true ? value : nil
    }

    private static func stringList(_ raw: Any?) -> [String] {
        if let values = raw as? [Any] {
            return values.map { String(describing: $0).trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
        guard let text = raw as? String else { return [] }
        return text.components(separatedBy: CharacterSet(charactersIn: "\n,，"))
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}

private extension Int64 {
    var clampedToAtLeastOne: Int64 { Swift.max(1, self) }
}
