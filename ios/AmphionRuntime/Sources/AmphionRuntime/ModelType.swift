import Foundation

/// 与 Android `ModelType` 完全对齐。
public enum ModelType: String {
    case transducer
    case paraformer
    case zipformer2_ctc
    case nemo_ctc

    /// 与 Android `ModelType.fromManifestString` 同义。
    public static func from(manifestString s: String?) -> ModelType {
        guard let raw = s?.lowercased().trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty else {
            return .transducer
        }
        switch raw {
        case "zipformer", "zipformer2", "transducer":
            return .transducer
        case "paraformer":
            return .paraformer
        case "zipformer2_ctc", "zipformer2-ctc", "ctc":
            return .zipformer2_ctc
        case "nemo_ctc", "nemo-ctc", "nemo":
            return .nemo_ctc
        default:
            return .transducer
        }
    }
}
