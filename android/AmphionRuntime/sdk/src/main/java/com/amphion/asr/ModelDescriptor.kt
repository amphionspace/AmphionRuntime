package com.amphion.asr

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * manifest.json 反序列化结果。结构与 [tools/asr/MODEL_LAYOUT.md] 中描述一致。
 */
public data class ModelDescriptor(
    public val manifestVersion: Int,
    public val modelId: String,
    public val version: String,
    public val minSdkVersion: String,
    public val maxSdkVersion: String,
    public val modelType: String,
    public val decodingMethod: String,
    public val sampleRate: Int,
    public val featureDim: Int,
    public val files: List<ModelFile>,
    /**
     * 模型语言标识（manifest.json 的 `lang` 字段）。约定值如：
     * - `zh-en`：中英混合
     * - `yue-en`：粤英混合
     * - `en`、`zh` 等单语种
     *
     * 老版本 manifest 没有该字段时为 null；调用方可以据此做语言路由（如多模型切换 UI）。
     * 字段命名与值约定参考 `tools/asr/MODEL_LAYOUT.md`。
     */
    public val lang: String? = null,
) {
    /**
     * 从 JSON 字符串解析。失败时抛出 [IllegalArgumentException]。
     */
    public companion object {
        @JvmStatic
        @Throws(IllegalArgumentException::class)
        public fun fromJson(json: String): ModelDescriptor = try {
            val o = JSONObject(json)
            val files = o.optJSONArray("files") ?: JSONArray()
            ModelDescriptor(
                manifestVersion = o.getInt("manifest_version"),
                modelId = o.getString("model_id"),
                version = o.getString("version"),
                minSdkVersion = o.optString("min_sdk_version", "0.0.0"),
                maxSdkVersion = o.optString("max_sdk_version", "999.999.999"),
                modelType = o.getString("model_type"),
                decodingMethod = o.optString("decoding_method", "greedy_search"),
                sampleRate = o.getInt("sample_rate"),
                featureDim = o.getInt("feature_dim"),
                files = (0 until files.length()).map { i ->
                    val f = files.getJSONObject(i)
                    ModelFile(
                        name = f.getString("name"),
                        url = f.getString("url"),
                        sizeBytes = f.getLong("size_bytes"),
                        sha256 = f.getString("sha256"),
                    )
                },
                lang = o.optString("lang", "").takeIf { it.isNotBlank() },
            )
        } catch (e: Exception) {
            throw IllegalArgumentException("invalid manifest.json: ${e.message}", e)
        }
    }
}

/**
 * manifest.files 中单个文件的元数据。
 */
public data class ModelFile(
    public val name: String,
    public val url: String,
    public val sizeBytes: Long,
    public val sha256: String,
)

/** 已下载到本地的一份模型。 */
public data class LocalModel(
    public val modelId: String,
    public val version: String,
    public val dir: File,
    /**
     * 模型语言标识，来自 [dir] 内 manifest.json 的 `lang` 字段。
     * manifest 不存在或缺少 `lang` 时为 null。语义同 [ModelDescriptor.lang]。
     */
    public val lang: String? = null,
)
