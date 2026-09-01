import Foundation
import SherpaOnnxBinary

internal final class SpeakerDiarizationRuntime {
    private let segmentationPath: URL
    private let embeddingPath: URL

    init(auxiliaryModelDirectory: URL) {
        segmentationPath = auxiliaryModelDirectory.appendingPathComponent("dingqiao/pyannote-segmentation-3.0.onnx")
        embeddingPath = auxiliaryModelDirectory.appendingPathComponent("dingqiao/eres2net.onnx")
    }

    var isAvailable: Bool {
        FileManager.default.fileExists(atPath: segmentationPath.path) &&
        FileManager.default.fileExists(atPath: embeddingPath.path)
    }

    func process(samples: [Float], maxSpeakers: Int) -> DingqiaoSpeakerDiarizationResult {
        guard isAvailable else { return degraded(.modelUnavailable, "speaker diarization models are unavailable") }
        guard !samples.isEmpty else { return degraded(.inferenceUnavailable, "session PCM is empty") }
        let started = DispatchTime.now().uptimeNanoseconds
        guard let segmenter = SherpaOnnxCreateSpeakerTurnSegmenter(segmentationPath.path) else {
            return degraded(.inferenceUnavailable, "speaker segmentation runtime creation failed")
        }
        defer { SherpaOnnxDestroySpeakerTurnSegmenter(segmenter) }
        var count: Int32 = 0
        let rawSegments = samples.withUnsafeBufferPointer { buffer in
            SherpaOnnxSpeakerTurnSegmenterProcess(
                segmenter, buffer.baseAddress, Int32(buffer.count), &count
            )
        }
        guard count == 0 || rawSegments != nil else {
            return degraded(.inferenceUnavailable, "speaker segmentation inference failed")
        }
        defer { SherpaOnnxDestroySpeakerTurnSegments(rawSegments) }
        let segments = rawSegments.map { pointer in
            (0..<Int(count)).map { pointer[$0] }
        } ?? []
        let elapsed = Int64((DispatchTime.now().uptimeNanoseconds - started) / 1_000_000)
        let turns = segments.compactMap { segment -> DingqiaoSpeakerTurn? in
            guard segment.speaker_index >= 0, Int(segment.speaker_index) < maxSpeakers else { return nil }
            let primary = Int(segment.speaker_index)
            let secondaries = (0..<min(3, maxSpeakers)).filter {
                $0 != primary && (Int(segment.speaker_mask) & (1 << $0)) != 0
            }
            return DingqiaoSpeakerTurn(
                beginTime: Int(segment.start_sample) * 1_000 / 16_000,
                endTime: Int(segment.end_sample) * 1_000 / 16_000,
                speakerIndex: primary,
                secondarySpeakerIndexes: secondaries,
                confidence: 1,
                overlap: !secondaries.isEmpty
            )
        }
        let speakerCount = min(maxSpeakers, Set(turns.flatMap {
            [$0.speakerIndex] + $0.secondarySpeakerIndexes
        }).count)
        let audioMs = max(1, samples.count * 1_000 / 16_000)
        return DingqiaoSpeakerDiarizationResult(speakerTurns: turns, speakerCount: speakerCount,
                                                inferenceMs: elapsed, rtf: Float(elapsed) / Float(audioMs))
    }

    func degraded(_ reason: DingqiaoSpeakerDiarizationDegradedReason, _ message: String) -> DingqiaoSpeakerDiarizationResult {
        DingqiaoSpeakerDiarizationResult(degraded: true, degradedReason: reason, degradedMessage: message)
    }
}
