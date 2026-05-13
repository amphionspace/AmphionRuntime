import Foundation

/// 与 [shared/api-spec/manifest.schema.json](../../../../shared/api-spec/manifest.schema.json) 一致；
/// 业务方调 ModelManager 拿到的就是这个结构。
public struct ModelDescriptor: Codable, Equatable {
    public let modelId: String
    public let version: String
    public let url: String?
    public let sha256: String?
    public let sizeBytes: Int64?
    public let lang: String?
    public let modelType: String?
    public let sampleRate: Int?
    public let featureDim: Int?
    public let decodingMethod: String?
    public let maxActivePaths: Int?
    public let files: [String]?

    public init(
        modelId: String,
        version: String,
        url: String? = nil,
        sha256: String? = nil,
        sizeBytes: Int64? = nil,
        lang: String? = nil,
        modelType: String? = nil,
        sampleRate: Int? = nil,
        featureDim: Int? = nil,
        decodingMethod: String? = nil,
        maxActivePaths: Int? = nil,
        files: [String]? = nil
    ) {
        self.modelId = modelId
        self.version = version
        self.url = url
        self.sha256 = sha256
        self.sizeBytes = sizeBytes
        self.lang = lang
        self.modelType = modelType
        self.sampleRate = sampleRate
        self.featureDim = featureDim
        self.decodingMethod = decodingMethod
        self.maxActivePaths = maxActivePaths
        self.files = files
    }

    enum CodingKeys: String, CodingKey {
        case modelId = "model_id"
        case version
        case url
        case sha256
        case sizeBytes = "size_bytes"
        case lang
        case modelType = "model_type"
        case sampleRate = "sample_rate"
        case featureDim = "feature_dim"
        case decodingMethod = "decoding_method"
        case maxActivePaths = "max_active_paths"
        case files
    }
}
