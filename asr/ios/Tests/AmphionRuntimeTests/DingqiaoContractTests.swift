import XCTest
@testable import AmphionRuntime

final class DingqiaoContractTests: XCTestCase {
    private let create = DingqiaoCreateEngineParams()

    func testDeviceLicenseFingerprintMatchesCrossPlatformContract() {
        XCTAssertEqual(
            DingqiaoSpeechRecognizeSdk.shared.deviceLicenseFingerprint(
                deviceSerial: "  abc ", deviceIdSaltId: "salt"
            ),
            "61A656ED760F8E7082B49FBF5F7CF213581FBC7C12CFDC9A2DBAC0BADD2C6983"
        )
    }

    func testRecognizerModePriorityAndFallback() throws {
        let engineLong = DingqiaoCreateEngineParams(extraParams: ["recognizerMode": "long"])
        var start = DingqiaoStartParams(sessionId: "session_1")
        XCTAssertEqual(try DingqiaoParameterPolicy.parse(create: engineLong, start: start).recognizerMode, "long")

        start.extraParams["recognizerMode"] = "short"
        XCTAssertEqual(try DingqiaoParameterPolicy.parse(create: engineLong, start: start).recognizerMode, "short")

        start.extraParams.removeAll()
        start.extraParams["enableContinuousRecognition"] = true
        XCTAssertEqual(try DingqiaoParameterPolicy.parse(create: create, start: start).recognizerMode, "long")
    }

    func testDisablePrepackMatchesCompatibleHostPolicy() {
        XCTAssertTrue(DingqiaoParameterPolicy.disablePrepack(create))
        XCTAssertFalse(DingqiaoParameterPolicy.disablePrepack(
            DingqiaoCreateEngineParams(extraParams: ["disablePrepack": false])
        ))
        XCTAssertFalse(DingqiaoParameterPolicy.disablePrepack(
            DingqiaoCreateEngineParams(extraParams: ["disablePrepack": "0"])
        ))
        XCTAssertTrue(DingqiaoParameterPolicy.disablePrepack(
            DingqiaoCreateEngineParams(extraParams: ["disablePrepack": Double.nan])
        ))
    }

    func testNumericParametersMatchSharedContract() throws {
        let start = DingqiaoStartParams(
            sessionId: "session-2",
            extraParams: [
                "recognitionMode": "1",
                "vadBegin": 100,
                "vadEnd": "12000",
                "maxAudioDuration": "99999999",
                "endpointMaxUtteranceMs": 1250.4,
            ]
        )
        let parsed = try DingqiaoParameterPolicy.parse(create: create, start: start)
        XCTAssertEqual(parsed.vadBeginMs, 500)
        XCTAssertEqual(parsed.vadEndMs, 10_000)
        XCTAssertEqual(parsed.maxAudioDurationMs, 28_800_000)
        XCTAssertEqual(parsed.endpointMaxUtteranceMs, 1_250)
    }

    func testVoiceprintAndDiarizationParametersParse() throws {
        let voiceprint = DingqiaoStartParams(
            sessionId: "vp",
            extraParams: [
                "enableVoiceprintVerification": true,
                "voiceprintIds": ["vp-1"],
                "speakerVadThreshold": 2.0,
                "speakerVadWindowMs": 100,
                "speakerVadHopMs": 4_000,
                "speakerVadConsecutiveBelow": 9,
            ]
        )
        let options = try DingqiaoParameterPolicy.parse(create: create, start: voiceprint)
        XCTAssertTrue(options.enableVoiceprintVerification)
        XCTAssertEqual(options.voiceprintIds, ["vp-1"])
        XCTAssertEqual(options.speakerVadThreshold, 1)
        XCTAssertEqual(options.speakerVadWindowMs, 500)
        XCTAssertEqual(options.speakerVadHopMs, 2_000)
        XCTAssertEqual(options.speakerVadConsecutiveBelow, 5)

        let diarization = DingqiaoStartParams(
            sessionId: "diarization",
            speakerDiarization: DingqiaoSpeakerDiarizationConfig()
        )
        XCTAssertEqual(try DingqiaoParameterPolicy.parse(create: create, start: diarization)
            .speakerDiarizationMaxSpeakers, 4)

        let invalid = DingqiaoStartParams(sessionId: "bad_diarization",
                                          speakerDiarization: DingqiaoSpeakerDiarizationConfig(maxSpeakers: 5))
        XCTAssertThrowsError(try DingqiaoParameterPolicy.parse(create: create, start: invalid))
    }

    func testUnavailablePoliceEnhancementIsNotASilentNoOp() throws {
        let defaults = try DingqiaoParameterPolicy.parse(
            create: create, start: DingqiaoStartParams(sessionId: "police_default")
        )
        XCTAssertTrue(defaults.enablePoliceEnhancement)
        XCTAssertThrowsError(try DingqiaoParameterPolicy.validateRuntimeCapabilities(
            defaults, policeEnhancementAvailable: false
        ))

        let disabled = try DingqiaoParameterPolicy.parse(
            create: create,
            start: DingqiaoStartParams(sessionId: "police_off",
                                       extraParams: ["enablePoliceEnhancement": false])
        )
        XCTAssertNoThrow(try DingqiaoParameterPolicy.validateRuntimeCapabilities(
            disabled, policeEnhancementAvailable: false
        ))
    }

    func testSpeakerVadRejectsOnlyScoredNonTargetFinalText() {
        XCTAssertTrue(DingqiaoSpeakerVadFinalPolicy.shouldReject(
            enabled: true, text: "非目标说话人", similarity: 0.2, threshold: 0.35
        ))
        XCTAssertFalse(DingqiaoSpeakerVadFinalPolicy.shouldReject(
            enabled: true, text: "目标说话人", similarity: 0.8, threshold: 0.35
        ))
        XCTAssertFalse(DingqiaoSpeakerVadFinalPolicy.shouldReject(
            enabled: true, text: "缺少技术评分时保留结果", similarity: nil, threshold: 0.35
        ))
        XCTAssertFalse(DingqiaoSpeakerVadFinalPolicy.shouldReject(
            enabled: false, text: "功能关闭", similarity: 0.1, threshold: 0.35
        ))
    }

    func testMetadataFreeSharedPyannoteModelUsesPowersetBridge() throws {
        var repository = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { repository.deleteLastPathComponent() }
        let sharedModels = repository.appendingPathComponent("shared/models/asr", isDirectory: true)
        let runtime = SpeakerDiarizationRuntime(auxiliaryModelDirectory: sharedModels)
        XCTAssertTrue(runtime.isAvailable)

        let result = runtime.process(samples: Array(repeating: 0, count: 160_000), maxSpeakers: 3)
        XCTAssertFalse(result.degraded, result.degradedMessage ?? "unexpected diarization degradation")
        XCTAssertEqual(result.speakerCount, 0)
        XCTAssertTrue(result.speakerTurns.isEmpty)
    }

    func testTextPostProcessingUsesItnBeforePunctuation() {
        var calls: [String] = []
        let pipeline = DingqiaoTextPostProcessingPipeline(
            normalize: { value in calls.append("itn:\(value)"); return "N(\(value))" },
            punctuate: { value in calls.append("punct:\(value)"); return "P(\(value))" }
        )
        XCTAssertEqual(pipeline.process("一百二十三"), "P(N(一百二十三))")
        XCTAssertEqual(calls, ["itn:一百二十三", "punct:N(一百二十三)"])
    }

    func testTextPostProcessingLayoutAcceptsPackagedRoot() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let packaged = root.appendingPathComponent("amphion-models", isDirectory: true)
        let punct = packaged.appendingPathComponent("punct-zhen/v1", isDirectory: true)
        let itn = packaged.appendingPathComponent("itn-zh/v1", isDirectory: true)
        try FileManager.default.createDirectory(at: punct, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: itn, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try Data().write(to: punct.appendingPathComponent("model.int8.ort"))
        try Data().write(to: itn.appendingPathComponent("zh_itn_tagger.fst"))
        try Data().write(to: itn.appendingPathComponent("zh_itn_verbalizer.fst"))

        let layout = DingqiaoTextPostProcessingLayout.resolve(root: root)
        XCTAssertTrue(layout.fullyAvailable)
        XCTAssertEqual(layout.punctuationModel?.lastPathComponent, "model.int8.ort")
    }

    func testUnavailableNativeOptionsFailBeforeEngineCreation() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try Data().write(to: directory.appendingPathComponent("tokens.txt"))

        let vad = AsrConfig(modelDir: directory).with(enableVad: true)
        XCTAssertThrowsError(try vad.validatedAndNormalized())

        let lm = AsrConfig(modelDir: directory).enableLmRescoring(
            modelPath: directory.appendingPathComponent("lm.onnx")
        )
        XCTAssertThrowsError(try lm.validatedAndNormalized())
    }

    func testHotwordsSelectCrossPlatformBeamDefaults() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        try Data().write(to: directory.appendingPathComponent("tokens.txt"))

        let defaults = try AsrConfig(modelDir: directory)
            .with(hotwords: ["余铭栋"])
            .validatedAndNormalized()
        XCTAssertEqual(defaults.decodingMethod, .modifiedBeamSearch)
        XCTAssertEqual(defaults.maxActivePaths, 8)

        let explicit = try AsrConfig(modelDir: directory)
            .with(hotwords: ["余铭栋"])
            .with(maxActivePaths: 12)
            .validatedAndNormalized()
        XCTAssertEqual(explicit.maxActivePaths, 12)
    }

    func testSharedOrtTransducerLayoutIsAcceptedAndPreferred() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        for name in [
            "tokens.txt", "bbpe.vocab",
            "encoder.int8.ort", "decoder.ort", "joiner.int8.ort",
            "encoder.int8.onnx", "decoder.onnx", "joiner.onnx",
        ] {
            try Data().write(to: directory.appendingPathComponent(name))
        }

        let resolved = try ModelLayout.resolve(modelDir: directory, type: .transducer)
        XCTAssertEqual(resolved.encoder?.lastPathComponent, "encoder.int8.ort")
        XCTAssertEqual(resolved.decoder?.lastPathComponent, "decoder.ort")
        XCTAssertEqual(resolved.joiner?.lastPathComponent, "joiner.int8.ort")
        XCTAssertEqual(resolved.bpeVocab?.lastPathComponent, "bbpe.vocab")
    }

    func testFinishProducesOneTerminalThenComplete() throws {
        var gate = DingqiaoLifecycleGate()
        try gate.start(sessionId: "s")
        XCTAssertTrue(try gate.acceptResult(sessionId: "s", isLast: false))
        XCTAssertEqual(try gate.finish(sessionId: "s"), .requestNativeFinish)
        XCTAssertFalse(gate.acceptsAudio(sessionId: "s"))
        XCTAssertTrue(gate.ignoresLateAudio(sessionId: "s"))
        XCTAssertEqual(try gate.finish(sessionId: "s"), .noOp)
        XCTAssertTrue(try gate.acceptResult(sessionId: "s", isLast: true))
        XCTAssertFalse(try gate.acceptResult(sessionId: "s", isLast: true))
        XCTAssertTrue(gate.complete(sessionId: "s"))
        XCTAssertFalse(gate.complete(sessionId: "s"))
        XCTAssertFalse(gate.isBusy)
    }

    func testLastBeforeFinishIsRejected() throws {
        var gate = DingqiaoLifecycleGate()
        try gate.start(sessionId: "s")
        XCTAssertThrowsError(try gate.acceptResult(sessionId: "s", isLast: true))
    }

    func testCancelSuppressesResultsAndComplete() throws {
        var gate = DingqiaoLifecycleGate()
        try gate.start(sessionId: "s")
        XCTAssertEqual(try gate.cancel(sessionId: "s"), .closeWithoutCallbacks)
        XCTAssertFalse(try gate.acceptResult(sessionId: "s", isLast: true))
        XCTAssertFalse(gate.complete(sessionId: "s"))
        XCTAssertFalse(gate.isBusy)
    }

    func testShutdownWaitsForFinishingSession() throws {
        var gate = DingqiaoLifecycleGate()
        try gate.start(sessionId: "s")
        _ = try gate.finish(sessionId: "s")
        XCTAssertEqual(gate.shutdown(), .noOp)
        XCTAssertTrue(gate.isBusy)
        XCTAssertTrue(try gate.acceptResult(sessionId: "s", isLast: true))
        XCTAssertTrue(gate.complete(sessionId: "s"))
        XCTAssertTrue(gate.isShutdown)
    }

    func testVadBeginPureSilenceTimesOutAtExactBoundary() {
        let tracker = InitialSilenceTracker(timeoutMs: 1_000)
        for _ in 0..<49 { XCTAssertFalse(tracker.observe(Array(repeating: 0, count: 320))) }
        XCTAssertTrue(tracker.observe(Array(repeating: 0, count: 320)))
        XCTAssertTrue(tracker.timedOut)
    }

    func testVadBeginAsrEvidencePermanentlyDisarmsTimeout() {
        let tracker = InitialSilenceTracker(timeoutMs: 500)
        XCTAssertFalse(tracker.observe(Array(repeating: 0, count: 320)))
        tracker.observeAsr(text: "speech", tokenCount: 0)
        XCTAssertFalse(tracker.observe(Array(repeating: 0, count: 16_000)))
        XCTAssertFalse(tracker.timedOut)
    }

    func testVadBeginSteadyHighEnergyIsNotSpeech() {
        let tracker = InitialSilenceTracker(timeoutMs: 500)
        let steady = (0..<8_000).map { $0.isMultiple(of: 2) ? Float(0.02) : Float(-0.02) }
        XCTAssertTrue(tracker.observe(steady))
    }

    func testVadBeginVaryingSpeechLikeSignalDisarmsTimeout() {
        let tracker = InitialSilenceTracker(timeoutMs: 500)
        var signal: [Float] = []
        for level: Float in [0.02, 0.08, 0.03, 0.12] {
            signal += (0..<320).map { $0 % 20 < 10 ? level : -level }
        }
        XCTAssertFalse(tracker.observe(signal))
        XCTAssertFalse(tracker.observe(Array(repeating: 0, count: 16_000)))
        XCTAssertFalse(tracker.timedOut)
    }
}
