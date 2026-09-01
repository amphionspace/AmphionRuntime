import Foundation

internal final class VoiceprintRuntime {
    private let workPath: URL
    private let modelPath: URL
    private let lock = NSLock()
    private var extractor: SherpaOnnxSpeakerEmbeddingExtractorWrapper?

    init(workPath: URL, auxiliaryModelDirectory: URL) {
        self.workPath = workPath
        self.modelPath = auxiliaryModelDirectory.appendingPathComponent("dingqiao/eres2net.onnx")
    }

    var isAvailable: Bool { FileManager.default.fileExists(atPath: modelPath.path) }

    func preload() -> Bool {
        guard isAvailable else { return false }
        do {
            lock.lock(); defer { lock.unlock() }
            try ensureExtractorLocked()
            return true
        } catch {
            return false
        }
    }

    func register(_ params: DingqiaoVoiceprintRegisterParams) -> DingqiaoVoiceprintRegisterResult {
        guard params.audioInfo.audioType == "pcm", params.audioInfo.sampleRate == 16_000,
              params.audioInfo.sampleBit == 16, params.audioInfo.soundChannel == 1 else {
            return failure(DingqiaoErrorCode.voiceprintRegisterFailed,
                           "audio must be PCM 16 kHz / 16 bit / mono")
        }
        guard params.samplePaths.count >= DINGQIAO_VOICEPRINT_MIN_SAMPLES else {
            return failure(DingqiaoErrorCode.voiceprintSampleCount,
                           "sample count must be >= \(DINGQIAO_VOICEPRINT_MIN_SAMPLES)")
        }
        guard isAvailable else {
            return failure(DingqiaoErrorCode.voiceprintRegisterFailed, "speaker model not found: \(modelPath.path)")
        }
        do {
            let segments = try params.samplePaths.map { try Self.readPcm16k(URL(fileURLWithPath: $0)) }
            for (index, segment) in segments.enumerated() {
                let seconds = Double(segment.count) / 16_000
                guard (Double(DINGQIAO_VOICEPRINT_MIN_SEC)...Double(DINGQIAO_VOICEPRINT_MAX_SEC))
                    .contains(seconds) else {
                    return failure(DingqiaoErrorCode.voiceprintSampleDuration,
                                   "sample duration must be \(DINGQIAO_VOICEPRINT_MIN_SEC)s.." +
                                   "\(DINGQIAO_VOICEPRINT_MAX_SEC)s: \(params.samplePaths[index])")
                }
            }
            let embeddings = try segments.map(computeEmbedding)
            let merged = Self.normalize(Self.mean(embeddings))
            let id = "vp-\(UUID().uuidString.lowercased())"
            try save(id: id, embedding: merged, sampleName: URL(fileURLWithPath: params.samplePaths[0]).lastPathComponent)
            return DingqiaoVoiceprintRegisterResult(voiceprintId: [id: URL(fileURLWithPath: params.samplePaths[0]).lastPathComponent],
                                                    status: 0, message: "registered")
        } catch {
            return failure(DingqiaoErrorCode.voiceprintRegisterFailed, String(describing: error))
        }
    }

    func delete(_ id: String) throws -> Bool {
        guard Self.validId(id) else { throw RuntimeError.invalidVoiceprintId }
        let dir = root.appendingPathComponent(id, isDirectory: true)
        guard FileManager.default.fileExists(atPath: dir.path) else { return false }
        try FileManager.default.removeItem(at: dir)
        return true
    }

    func contains(_ id: String) -> Bool {
        guard Self.validId(id) else { return false }
        return FileManager.default.fileExists(
            atPath: root.appendingPathComponent(id, isDirectory: true)
                .appendingPathComponent("embedding.bin").path
        )
    }

    func similarity(samples: [Float], ids: [String]) -> Float? {
        guard !samples.isEmpty, !ids.isEmpty else { return nil }
        let enrolled = ids.compactMap(load)
        guard !enrolled.isEmpty, let current = try? computeEmbedding(samples) else { return nil }
        let target = Self.normalize(Self.mean(enrolled))
        return zip(target, current).reduce(Float(0)) { $0 + $1.0 * $1.1 }
    }

    private var root: URL { workPath.appendingPathComponent("voiceprints", isDirectory: true) }

    private func computeEmbedding(_ samples: [Float]) throws -> [Float] {
        lock.lock()
        defer { lock.unlock() }
            try ensureExtractorLocked()
            guard let extractor, extractor.impl != nil else { throw RuntimeError.extractorUnavailable }
            let stream = extractor.createStream()
            stream.acceptWaveform(samples: samples, sampleRate: 16_000)
            stream.inputFinished()
            let result = extractor.compute(stream: stream)
            guard !result.isEmpty else { throw RuntimeError.embeddingUnavailable }
            return Self.normalize(result)
    }

    private func ensureExtractorLocked() throws {
        if extractor == nil {
            var config = sherpaOnnxSpeakerEmbeddingExtractorConfig(
                model: modelPath.path, numThreads: 2, provider: "cpu;disableprepacking=1")
            extractor = withUnsafePointer(to: &config) {
                SherpaOnnxSpeakerEmbeddingExtractorWrapper(config: $0)
            }
        }
        guard extractor?.impl != nil else { throw RuntimeError.extractorUnavailable }
    }

    private func save(id: String, embedding: [Float], sampleName: String) throws {
        let dir = root.appendingPathComponent(id, isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var data = Data()
        var dim = Int32(embedding.count).littleEndian
        withUnsafeBytes(of: &dim) { data.append(contentsOf: $0) }
        for value in embedding {
            var bits = value.bitPattern.littleEndian
            withUnsafeBytes(of: &bits) { data.append(contentsOf: $0) }
        }
        try data.write(to: dir.appendingPathComponent("embedding.bin"), options: .atomic)
        let metadata = ["voiceprintId": id, "sample": sampleName]
        try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys])
            .write(to: dir.appendingPathComponent("meta.json"), options: .atomic)
    }

    private func load(_ id: String) -> [Float]? {
        guard Self.validId(id), let data = try? Data(contentsOf: root.appendingPathComponent(id).appendingPathComponent("embedding.bin")),
              data.count >= 4 else { return nil }
        let dim = data.withUnsafeBytes { Int(Int32(littleEndian: $0.loadUnaligned(as: Int32.self))) }
        guard dim > 0, data.count == 4 + dim * 4 else { return nil }
        return (0..<dim).map { index in
            let bits = data.withUnsafeBytes { raw in
                UInt32(littleEndian: raw.loadUnaligned(fromByteOffset: 4 + index * 4, as: UInt32.self))
            }
            return Float(bitPattern: bits)
        }
    }

    private func failure(_ code: Int, _ message: String) -> DingqiaoVoiceprintRegisterResult {
        DingqiaoVoiceprintRegisterResult(status: code, message: message)
    }

    private static func validId(_ id: String) -> Bool {
        id.range(of: #"^vp-[A-Za-z0-9-]+$"#, options: .regularExpression) != nil
    }
    private static func mean(_ values: [[Float]]) -> [Float] {
        guard let first = values.first, values.allSatisfy({ $0.count == first.count }) else { return [] }
        var result = Array(repeating: Float(0), count: first.count)
        for value in values { for i in result.indices { result[i] += value[i] } }
        return result.map { $0 / Float(values.count) }
    }
    private static func normalize(_ values: [Float]) -> [Float] {
        let norm = max(sqrt(values.reduce(Float(0)) { $0 + $1 * $1 }), 1e-12)
        return values.map { $0 / norm }
    }

    private static func readPcm16k(_ url: URL) throws -> [Float] {
        let data = try Data(contentsOf: url)
        var start = 0
        if data.count >= 44, String(data: data.prefix(4), encoding: .ascii) == "RIFF" {
            var offset = 12
            var validFormat = false
            while offset + 8 <= data.count {
                let id = String(data: data[offset..<(offset + 4)], encoding: .ascii)
                let size = Int(UInt32(data[offset + 4]) | UInt32(data[offset + 5]) << 8 |
                               UInt32(data[offset + 6]) << 16 | UInt32(data[offset + 7]) << 24)
                guard offset + 8 + size <= data.count else { throw RuntimeError.invalidPcm }
                if id == "fmt ", size >= 16 {
                    let base = offset + 8
                    let format = UInt16(data[base]) | UInt16(data[base + 1]) << 8
                    let channels = UInt16(data[base + 2]) | UInt16(data[base + 3]) << 8
                    let rate = UInt32(data[base + 4]) | UInt32(data[base + 5]) << 8 |
                        UInt32(data[base + 6]) << 16 | UInt32(data[base + 7]) << 24
                    let bits = UInt16(data[base + 14]) | UInt16(data[base + 15]) << 8
                    validFormat = format == 1 && channels == 1 && rate == 16_000 && bits == 16
                }
                if id == "data" { start = offset + 8; break }
                offset += 8 + size + size % 2
            }
            guard validFormat else { throw RuntimeError.invalidPcm }
        }
        guard start < data.count, (data.count - start).isMultiple(of: 2) else { throw RuntimeError.invalidPcm }
        return stride(from: start, to: data.count, by: 2).map { offset in
            let value = Int16(bitPattern: UInt16(data[offset]) | UInt16(data[offset + 1]) << 8)
            return Float(value) / 32768
        }
    }

    private enum RuntimeError: Error { case invalidVoiceprintId, extractorUnavailable, embeddingUnavailable, invalidPcm }
}
