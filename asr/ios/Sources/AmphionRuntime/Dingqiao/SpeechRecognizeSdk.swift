import Foundation
import CryptoKit

/// iOS 鼎桥兼容入口。模型目录由宿主或交付包显式配置，避免运行时隐式下载。
public final class DingqiaoSpeechRecognizeSdk {
    public static let shared = DingqiaoSpeechRecognizeSdk()

    private let lock = NSLock()
    private let operationQueue = DispatchQueue(label: "com.amphion.dingqiao.ios.runtime")
    private var workPath: URL?
    private var modelDirectory: URL?
    private var auxiliaryModelDirectory: URL?
    private var preparedConfig: AsrConfig?
    private var modelGeneration: UInt64 = 0
    private var activeEngines: [ObjectIdentifier: DingqiaoRecognitionEngine] = [:]
    private var cachedVoiceprintRuntime: VoiceprintRuntime?
    private var cachedTextPostProcessor: DingqiaoTextPostProcessor?

    private init() {}

    public func setWorkPath(_ path: URL) throws {
        try FileManager.default.createDirectory(at: path, withIntermediateDirectories: true)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path.path, isDirectory: &isDirectory),
              isDirectory.boolValue, FileManager.default.isWritableFile(atPath: path.path) else {
            throw DingqiaoParameterError.invalid("workPath must be a writable directory: \(path.path)")
        }
        lock.lock(); workPath = path; cachedVoiceprintRuntime = nil; lock.unlock()
    }

    public func setWorkPath(_ path: String) throws {
        try setWorkPath(URL(fileURLWithPath: path, isDirectory: true))
    }

    public func getWorkPath() -> URL? {
        lock.lock(); defer { lock.unlock() }
        return workPath
    }

    /// String form matching the Android/Harmony customer API.
    public func getWorkPathString() -> String { getWorkPath()?.path ?? "" }

    public func setLogLevel(_ level: AmphionLogLevel) {
        AsrSdk.shared.setLogLevel(level)
    }

    @available(*, deprecated, message: "Use the dedicated diagnostics artifact.")
    public func configureDiagnostics(_ options: DingqiaoDiagnosticOptions) {
        _ = options
    }

    public func exportDiagnostics(callback: DingqiaoDiagnosticExportCallback) {
        operationQueue.async {
            callback.onError(errorCode: DingqiaoErrorCode.internalError,
                             errorMessage: "diagnostics are unavailable in the normal iOS SDK build")
        }
    }

    public func deviceLicenseFingerprint(deviceSerial: String, deviceIdSaltId: String) -> String {
        let normalized = deviceSerial.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        let digest = SHA256.hash(data: Data((normalized + deviceIdSaltId).utf8))
        return digest.map { String(format: "%02X", $0) }.joined()
    }

    /// The API is present for source parity, but formal iOS device-bound license verification is
    /// intentionally unavailable until the iOS signing identity contract is frozen.
    public func setLicense(_ licensePath: String, callback: DingqiaoLicenseActivationCallback) {
        guard FileManager.default.isReadableFile(atPath: licensePath) else {
            callback.onError(errorCode: DingqiaoErrorCode.licenseFileUnreadable,
                             errorMessage: "license file not readable: \(licensePath)")
            return
        }
        callback.onError(errorCode: DingqiaoErrorCode.licenseActivationFailed,
                         errorMessage: "formal iOS device-bound license verification is not available")
    }

    public func getLicenseInfo() throws -> DingqiaoLicenseInfo {
        throw DingqiaoParameterError.unsupported("formal iOS license is not set")
    }

    /// iOS 平台资源扩展：指定交付包内或 App 沙箱中的公共 ASR 模型目录。
    public func setModelDirectory(_ directory: URL) {
        lock.lock()
        modelGeneration &+= 1
        modelDirectory = directory
        preparedConfig = nil
        lock.unlock()
    }

    /// Shared auxiliary model root. Expected children include `dingqiao/eres2net.onnx`,
    /// `dingqiao/pyannote-segmentation-3.0.onnx`, and `police/lac/v1/`.
    public func setAuxiliaryModelDirectory(_ directory: URL) {
        lock.lock()
        auxiliaryModelDirectory = directory
        cachedVoiceprintRuntime = nil
        cachedTextPostProcessor = nil
        lock.unlock()
    }

    public func isVoiceprintAvailable() -> Bool {
        guard let runtime = try? makeVoiceprintRuntime() else { return false }
        return runtime.isAvailable
    }

    public func isSpeakerDiarizationAvailable() -> Bool {
        makeDiarizationRuntime()?.isAvailable == true
    }

    /// Preflight all public cross-platform capabilities against the resources and runtime that
    /// are actually present in this iOS delivery. This avoids treating a parsed parameter as an
    /// implemented feature.
    public func runtimeCapabilities() -> DingqiaoRuntimeCapabilities {
        let text = makeTextPostProcessor()
        let voiceprint = isVoiceprintAvailable()
        return DingqiaoRuntimeCapabilities(
            voiceprint: voiceprint,
            speakerVad: voiceprint,
            speakerDiarization: isSpeakerDiarizationAvailable(),
            inverseTextNormalization: text?.isItnAvailable == true,
            punctuation: text?.isPunctuationAvailable == true,
            policeEnhancement: false,
            formalOfflineLicense: false,
            diagnosticSchemaV2: false
        )
    }

    public func prepareRuntime(callback: DingqiaoPrepareRuntimeCallback) {
        operationQueue.async { [weak self, callback] in
            guard let self else { return }
            do {
                let snapshot = self.lockedModelSnapshot()
                let directory = snapshot.directory
                guard let directory else {
                    throw DingqiaoParameterError.invalid("setModelDirectory must be called before prepareRuntime")
                }
                AsrSdk.shared.start()
                let config = try AsrConfig(modelDir: directory).validatedAndNormalized()
                // onReady 是模型可实际创建 native recognizer 的承诺，不只是文件存在通知。
                let probe = try AsrEngine(config: config)
                probe.close()
                self.lock.lock()
                guard self.modelGeneration == snapshot.generation,
                      self.modelDirectory == directory else {
                    self.lock.unlock()
                    throw DingqiaoParameterError.invalid("model directory changed while prepareRuntime was running")
                }
                self.preparedConfig = config
                self.lock.unlock()
                callback.onReady()
            } catch {
                callback.onError(
                    errorCode: DingqiaoErrorCode.engineNotInitialized,
                    errorMessage: String(describing: error)
                )
            }
        }
    }

    public func createEngine(_ params: DingqiaoCreateEngineParams) throws -> DingqiaoSpeechRecognitionEngine {
        try DingqiaoParameterPolicy.validateCreate(params)
        let config: AsrConfig? = {
            lock.lock(); defer { lock.unlock() }
            return preparedConfig
        }()
        guard var config else {
            throw DingqiaoParameterError.invalid("prepareRuntime must succeed before createEngine")
        }
        config = config.with(disablePrepack: DingqiaoParameterPolicy.disablePrepack(params))
        let systemLexicon = DingqiaoParameterPolicy.systemGeneralLexicon(params)
        if !systemLexicon.isEmpty { config = config.with(hotwords: systemLexicon) }
        let engine = DingqiaoRecognitionEngine(
            createParams: params, baseConfig: config,
            voiceprintRuntime: try? makeVoiceprintRuntime(),
            diarizationRuntime: makeDiarizationRuntime(),
            textPostProcessor: makeTextPostProcessor(),
            onShutdown: { [weak self] engine in
                guard let self else { return }
                self.lock.lock()
                self.activeEngines.removeValue(forKey: ObjectIdentifier(engine))
                self.lock.unlock()
            }
        )
        lock.lock(); activeEngines[ObjectIdentifier(engine)] = engine; lock.unlock()
        return engine
    }

    public func createEngine(
        _ params: DingqiaoCreateEngineParams,
        callback: DingqiaoCreateEngineCallback
    ) {
        operationQueue.async { [weak self, callback] in
            guard let self else { return }
            do {
                callback.onSuccess(engine: try self.createEngine(params))
            } catch {
                callback.onError(
                    errorCode: DingqiaoErrorCode.createEngineFailed,
                    errorMessage: String(describing: error)
                )
            }
        }
    }

    public func createEngineAsync(
        _ params: DingqiaoCreateEngineParams,
        callback: DingqiaoCreateEngineCallback
    ) {
        createEngine(params, callback: callback)
    }

    private func lockedModelSnapshot() -> (directory: URL?, generation: UInt64) {
        lock.lock(); defer { lock.unlock() }
        return (modelDirectory, modelGeneration)
    }

    public func registerVoiceprint(_ params: DingqiaoVoiceprintRegisterParams) -> DingqiaoVoiceprintRegisterResult {
        do { return try makeVoiceprintRuntime().register(params) }
        catch { return DingqiaoVoiceprintRegisterResult(status: DingqiaoErrorCode.voiceprintRegisterFailed,
                                                        message: String(describing: error)) }
    }

    public func registerVoiceprint(_ params: DingqiaoVoiceprintRegisterParams,
                                   callback: DingqiaoVoiceprintRegisterCallback) {
        operationQueue.async { [weak self, callback] in
            guard let self else { return }
            let result = self.registerVoiceprint(params)
            if result.status == 0 {
                callback.onResult(result: result)
            } else {
                callback.onError(errorCode: result.status, errorMessage: result.message)
            }
        }
    }

    public func deleteVoiceprint(_ voiceprintId: String) throws -> Bool {
        try makeVoiceprintRuntime().delete(voiceprintId)
    }

    public func hasVoiceprint(_ voiceprintId: String) -> Bool {
        (try? makeVoiceprintRuntime().contains(voiceprintId)) == true
    }

    public func preloadVoiceprintModel() -> Bool {
        (try? makeVoiceprintRuntime().preload()) == true
    }

    /// L2: close active engines and invalidate the prepared recognizer configuration while
    /// retaining process-level SDK state and all on-disk models/voiceprints.
    public func unloadModel() {
        let engines: [DingqiaoRecognitionEngine] = {
            lock.lock(); defer { lock.unlock() }
            modelGeneration &+= 1
            preparedConfig = nil
            // L2 parity: release in-memory ASR, punctuation/ITN and speaker extractor state.
            // Model files and persisted voiceprint embeddings remain on disk.
            cachedVoiceprintRuntime = nil
            cachedTextPostProcessor = nil
            return Array(activeEngines.values)
        }()
        engines.forEach { $0.shutdown() }
    }

    /// L1: unload models and return the iOS runtime facade to its unprepared state.
    public func unloadRuntime() {
        unloadModel()
        AsrSdk.shared.stop()
    }

    private func makeVoiceprintRuntime() throws -> VoiceprintRuntime {
        lock.lock(); defer { lock.unlock() }
        if let cachedVoiceprintRuntime { return cachedVoiceprintRuntime }
        guard let workPath else { throw DingqiaoParameterError.invalid("setWorkPath must be called first") }
        guard let auxiliaryModelDirectory else {
            throw DingqiaoParameterError.invalid("setAuxiliaryModelDirectory must be called first")
        }
        let runtime = VoiceprintRuntime(workPath: workPath,
                                        auxiliaryModelDirectory: auxiliaryModelDirectory)
        cachedVoiceprintRuntime = runtime
        return runtime
    }

    private func makeDiarizationRuntime() -> SpeakerDiarizationRuntime? {
        let models: URL? = { lock.lock(); defer { lock.unlock() }; return auxiliaryModelDirectory }()
        return models.map(SpeakerDiarizationRuntime.init(auxiliaryModelDirectory:))
    }

    private func makeTextPostProcessor() -> DingqiaoTextPostProcessor? {
        lock.lock(); defer { lock.unlock() }
        if let cachedTextPostProcessor { return cachedTextPostProcessor }
        guard let auxiliaryModelDirectory else { return nil }
        let runtime = DingqiaoTextPostProcessor(auxiliaryModelDirectory: auxiliaryModelDirectory)
        cachedTextPostProcessor = runtime
        return runtime
    }
}

public typealias SpeechRecognizeSdk = DingqiaoSpeechRecognizeSdk
