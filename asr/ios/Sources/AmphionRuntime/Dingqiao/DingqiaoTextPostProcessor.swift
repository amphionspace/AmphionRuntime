import Foundation
import SherpaOnnxBinary

internal struct DingqiaoTextPostProcessingLayout: Equatable {
    let punctuationModel: URL?
    let itnTagger: URL?
    let itnVerbalizer: URL?

    var punctuationAvailable: Bool { punctuationModel != nil }
    var itnAvailable: Bool { itnTagger != nil && itnVerbalizer != nil }
    var fullyAvailable: Bool { punctuationAvailable && itnAvailable }

    static func resolve(root: URL) -> DingqiaoTextPostProcessingLayout {
        let roots = [root, root.appendingPathComponent("amphion-models", isDirectory: true)]
        return DingqiaoTextPostProcessingLayout(
            punctuationModel: firstExisting(
                roots.flatMap { base in
                    [
                        base.appendingPathComponent("punct-zhen/v1/model.int8.ort"),
                        base.appendingPathComponent("punct-zhen/v1/model.int8.onnx"),
                    ]
                }
            ),
            itnTagger: firstExisting(
                roots.map { $0.appendingPathComponent("itn-zh/v1/zh_itn_tagger.fst") }
            ),
            itnVerbalizer: firstExisting(
                roots.map { $0.appendingPathComponent("itn-zh/v1/zh_itn_verbalizer.fst") }
            )
        )
    }

    private static func firstExisting(_ candidates: [URL]) -> URL? {
        candidates.first { FileManager.default.isReadableFile(atPath: $0.path) }
    }
}

/// A small seam that makes the cross-platform processing order independently testable.
/// Android and Harmony both publish `ITN -> punctuation`; changing the order is an API-level
/// behavior change rather than a UI detail.
internal struct DingqiaoTextPostProcessingPipeline {
    let normalize: ((String) -> String)?
    let punctuate: ((String) -> String)?

    func process(_ text: String) -> String {
        guard !text.isEmpty else { return text }
        let normalized = normalize?(text) ?? text
        return punctuate?(normalized) ?? normalized
    }
}

/// Process-level immutable final-text resources. Calls are serialized because both native
/// processors own shared read-only state and final ordering must match the ASR callback order.
internal final class DingqiaoTextPostProcessor {
    let layout: DingqiaoTextPostProcessingLayout

    private let lock = NSLock()
    private let itn: WeitnEngine?
    private let punctuation: SherpaOnnxOfflinePunctuationWrapper?

    init(auxiliaryModelDirectory: URL) {
        layout = DingqiaoTextPostProcessingLayout.resolve(root: auxiliaryModelDirectory)

        if let tagger = layout.itnTagger, let verbalizer = layout.itnVerbalizer {
            itn = try? WeitnEngine(config: WeitnConfig(taggerFst: tagger, verbalizerFst: verbalizer))
        } else {
            itn = nil
        }

        if let model = layout.punctuationModel {
            let modelConfig = sherpaOnnxOfflinePunctuationModelConfig(
                ctTransformer: model.path, numThreads: 1, debug: 0,
                provider: "cpu;DisablePrepacking=1"
            )
            var config = sherpaOnnxOfflinePunctuationConfig(model: modelConfig)
            let created = withUnsafePointer(to: &config) {
                SherpaOnnxOfflinePunctuationWrapper(config: $0)
            }
            punctuation = created.ptr == nil ? nil : created
        } else {
            punctuation = nil
        }
    }

    var isItnAvailable: Bool { itn != nil }
    var isPunctuationAvailable: Bool { punctuation != nil }
    var isFullyAvailable: Bool { isItnAvailable && isPunctuationAvailable }

    func process(_ text: String) -> String {
        lock.lock(); defer { lock.unlock() }
        let pipeline = DingqiaoTextPostProcessingPipeline(
            normalize: itn.map { engine in { engine.normalize($0) } },
            punctuate: punctuation.map { engine in
                { Self.stripLeadingPunctuation(engine.addPunct(text: $0)) }
            }
        )
        return pipeline.process(text)
    }

    private static func stripLeadingPunctuation(_ text: String) -> String {
        let leading = CharacterSet(charactersIn: ",.;:?!，。、；：？！")
            .union(.whitespacesAndNewlines)
        return text.drop { character in
            character.unicodeScalars.allSatisfy { leading.contains($0) }
        }.description
    }
}
