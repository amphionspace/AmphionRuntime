import Foundation

/// 与 Android `ModelLayout` 一一对应：按 model_type 解析模型文件路径。
internal struct ResolvedFiles {
    var encoder: URL?
    var decoder: URL?
    var joiner: URL?
    var model: URL?
    let tokens: URL
    var bpeVocab: URL?
}

internal enum ModelLayout {

    static func resolve(modelDir: URL, type: ModelType) throws -> ResolvedFiles {
        let tokens = modelDir.appendingPathComponent("tokens.txt")
        if !FileManager.default.fileExists(atPath: tokens.path) {
            throw AsrError(code: .modelFileMissing, message: "missing tokens.txt under \(modelDir.path)")
        }
        switch type {
        case .transducer:
            let enc = pickFirst(
                modelDir,
                "encoder.int8.ort", "encoder.ort",
                "encoder.int8.onnx", "encoder.onnx", "encoder.fp16.onnx"
            )
            let dec = pickFirst(
                modelDir,
                "decoder.ort", "decoder.int8.ort",
                "decoder.onnx", "decoder.int8.onnx", "decoder.fp16.onnx"
            )
            let join = pickFirst(
                modelDir,
                "joiner.int8.ort", "joiner.ort",
                "joiner.int8.onnx", "joiner.onnx", "joiner.fp16.onnx"
            )
            guard let e = enc, let d = dec, let j = join else {
                throw AsrError(
                    code: .modelFileMissing,
                    message: "transducer requires encoder + decoder + joiner ONNX/ORT files under \(modelDir.path)"
                )
            }
            return ResolvedFiles(
                encoder: e,
                decoder: d,
                joiner: j,
                model: nil,
                tokens: tokens,
                bpeVocab: pickFirst(modelDir, "bbpe.vocab")
            )
        case .paraformer:
            let enc = pickFirst(modelDir, "encoder.int8.ort", "encoder.ort", "encoder.int8.onnx", "encoder.onnx")
            let dec = pickFirst(modelDir, "decoder.int8.ort", "decoder.ort", "decoder.int8.onnx", "decoder.onnx")
            guard let e = enc, let d = dec else {
                throw AsrError(
                    code: .modelFileMissing,
                    message: "paraformer requires encoder + decoder ONNX/ORT files under \(modelDir.path)"
                )
            }
            return ResolvedFiles(
                encoder: e,
                decoder: d,
                joiner: nil,
                model: nil,
                tokens: tokens,
                bpeVocab: nil
            )
        case .zipformer2_ctc, .nemo_ctc:
            guard let m = pickFirst(
                modelDir,
                "model.int8.ort", "model.ort",
                "model.int8.onnx", "model.onnx", "model.fp16.onnx"
            ) else {
                throw AsrError(
                    code: .modelFileMissing,
                    message: "\(type.rawValue) requires model ONNX/ORT file under \(modelDir.path)"
                )
            }
            return ResolvedFiles(
                encoder: nil,
                decoder: nil,
                joiner: nil,
                model: m,
                tokens: tokens,
                bpeVocab: nil
            )
        }
    }

    private static func pickFirst(_ dir: URL, _ names: String...) -> URL? {
        for n in names {
            let f = dir.appendingPathComponent(n)
            if FileManager.default.fileExists(atPath: f.path) { return f }
        }
        return nil
    }
}
