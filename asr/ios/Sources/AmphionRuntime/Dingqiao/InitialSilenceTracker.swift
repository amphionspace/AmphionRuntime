import Foundation

/// Chunk-invariant initial-silence gate shared by the Dingqiao adapter.
/// Acoustic energy alone never proves speech: only ASR evidence or speech-shaped energy/ZCR does.
internal final class InitialSilenceTracker {
    private let deadlineSamples: Int64
    private let windowSamples: Int
    private var observedSamples: Int64 = 0
    private var squareSum = 0.0
    private var samplesInWindow = 0
    private var zeroCrossings = 0
    private var previous: Float = 0
    private var hasPrevious = false
    private var speechLikeRun = 0
    private var minRms = Double.infinity
    private var maxRms = 0.0
    private(set) var isArmed = true
    private(set) var timedOut = false

    init(timeoutMs: Int, sampleRate: Int = 16_000) {
        deadlineSamples = Int64(timeoutMs) * Int64(sampleRate) / 1_000
        windowSamples = max(1, sampleRate / 50)
    }

    func observe(_ samples: [Float]) -> Bool {
        guard isArmed, !timedOut else { return false }
        for sample in samples {
            // The decision is made at the exact public PCM boundary. Samples after the deadline
            // are never inspected and therefore cannot reverse a timeout.
            if observedSamples >= deadlineSamples {
                timedOut = true; isArmed = false; return true
            }
            observedSamples += 1
            squareSum += Double(sample * sample)
            if hasPrevious, (sample >= 0) != (previous >= 0) { zeroCrossings += 1 }
            previous = sample; hasPrevious = true; samplesInWindow += 1
            if samplesInWindow == windowSamples { finishWindow() }
        }
        if observedSamples >= deadlineSamples, isArmed {
            timedOut = true; isArmed = false; return true
        }
        return false
    }

    func observeAsr(text: String, tokenCount: Int) {
        guard isArmed, !timedOut else { return }
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || tokenCount > 0 {
            isArmed = false
        }
    }

    private func finishWindow() {
        let rms = sqrt(squareSum / Double(max(1, samplesInWindow)))
        let zcr = Double(zeroCrossings) / Double(max(1, samplesInWindow - 1))
        let speechLike = rms >= 0.01 && (0.005...0.35).contains(zcr)
        if speechLike {
            speechLikeRun += 1; minRms = min(minRms, rms); maxRms = max(maxRms, rms)
            if speechLikeRun >= 3, maxRms >= minRms * 3 { isArmed = false }
        } else {
            speechLikeRun = 0; minRms = .infinity; maxRms = 0
        }
        squareSum = 0; samplesInWindow = 0; zeroCrossings = 0; hasPrevious = false
    }
}
