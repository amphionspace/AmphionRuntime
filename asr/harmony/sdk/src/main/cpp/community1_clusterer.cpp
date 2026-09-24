#include "community1_clusterer.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr int32_t kEmbeddingDim = 256;
constexpr int32_t kPldaDim = 128;
constexpr int32_t kLocalSpeakers = 3;
constexpr int32_t kFrames = 589;
constexpr float kAhcThreshold = 0.6F;
constexpr float kFa = 0.07F;
constexpr float kFb = 0.8F;
constexpr int32_t kMaxIters = 20;
constexpr float kPiFloor = 1e-7F;
constexpr char kMagic[] = "C1PLDA01";

template <typename T>
std::vector<T> CopyTypedArray(napi_env env, napi_value value,
                              napi_typedarray_type expected) {
  napi_typedarray_type actual;
  size_t length = 0;
  void* data = nullptr;
  napi_value buffer = nullptr;
  size_t byte_offset = 0;
  if (napi_get_typedarray_info(env, value, &actual, &length, &data, &buffer,
                               &byte_offset) != napi_ok ||
      actual != expected) {
    throw std::runtime_error("invalid Community-1 typed array");
  }
  napi_value byte_length_value = nullptr;
  uint32_t byte_length = 0;
  if (napi_get_named_property(env, value, "byteLength", &byte_length_value) != napi_ok ||
      napi_get_value_uint32(env, byte_length_value, &byte_length) != napi_ok ||
      byte_length % sizeof(T) != 0) {
    throw std::runtime_error("invalid Community-1 typed array byteLength");
  }
  const size_t element_count = static_cast<size_t>(byte_length) / sizeof(T);
  // Standard Node-API reports element count, while affected Harmony releases
  // report bytes. The JS view byteLength is authoritative in both cases.
  if (length != element_count && length != byte_length) {
    throw std::runtime_error("inconsistent Community-1 typed array length");
  }
  return std::vector<T>(static_cast<T*>(data),
                        static_cast<T*>(data) + element_count);
}

uint32_t ReadU32(const uint8_t*& cursor, const uint8_t* end) {
  if (end - cursor < 4) throw std::runtime_error("truncated Community-1 PLDA blob");
  uint32_t value = 0;
  std::memcpy(&value, cursor, sizeof(value));
  cursor += sizeof(value);
  return value;
}

std::vector<float> ReadFloats(const uint8_t*& cursor, const uint8_t* end,
                              size_t count) {
  const size_t bytes = count * sizeof(float);
  if (static_cast<size_t>(end - cursor) < bytes) {
    throw std::runtime_error("truncated Community-1 PLDA matrix");
  }
  std::vector<float> result(count);
  std::memcpy(result.data(), cursor, bytes);
  cursor += bytes;
  return result;
}

struct PldaParameters {
  std::vector<float> mean1;
  std::vector<float> lda;
  std::vector<float> mean2;
  std::vector<float> mu;
  std::vector<float> transform;
  std::vector<float> phi;

  static std::shared_ptr<PldaParameters> Parse(const std::vector<uint8_t>& bytes) {
    const uint8_t* cursor = bytes.data();
    const uint8_t* end = bytes.data() + bytes.size();
    if (bytes.size() < 20 || std::memcmp(cursor, kMagic, 8) != 0) {
      throw std::runtime_error("invalid Community-1 PLDA blob magic");
    }
    cursor += 8;
    const uint32_t version = ReadU32(cursor, end);
    const uint32_t embedding_dim = ReadU32(cursor, end);
    const uint32_t plda_dim = ReadU32(cursor, end);
    if (version != 1 || embedding_dim != kEmbeddingDim || plda_dim != kPldaDim) {
      throw std::runtime_error("unsupported Community-1 PLDA blob dimensions");
    }
    auto result = std::make_shared<PldaParameters>();
    result->mean1 = ReadFloats(cursor, end, kEmbeddingDim);
    result->lda = ReadFloats(cursor, end, kEmbeddingDim * kPldaDim);
    result->mean2 = ReadFloats(cursor, end, kPldaDim);
    result->mu = ReadFloats(cursor, end, kPldaDim);
    result->transform = ReadFloats(cursor, end, kPldaDim * kPldaDim);
    result->phi = ReadFloats(cursor, end, kPldaDim);
    if (cursor != end) throw std::runtime_error("unexpected Community-1 PLDA blob tail");
    return result;
  }

  std::vector<float> Transform(const std::vector<float>& embeddings,
                               int32_t rows) const {
    std::vector<float> result(static_cast<size_t>(rows) * kPldaDim);
    std::vector<float> centered(kEmbeddingDim);
    std::vector<float> xvec(kPldaDim);
    for (int32_t row = 0; row < rows; ++row) {
      const float* source = embeddings.data() + static_cast<size_t>(row) * kEmbeddingDim;
      float norm = 0.0F;
      for (int32_t d = 0; d < kEmbeddingDim; ++d) {
        centered[d] = source[d] - mean1[d];
        norm += centered[d] * centered[d];
      }
      norm = std::sqrt(std::max(norm, 1e-20F));
      const float first_scale = std::sqrt(static_cast<float>(kEmbeddingDim)) / norm;
      float xvec_norm = 0.0F;
      for (int32_t out = 0; out < kPldaDim; ++out) {
        float value = -mean2[out];
        for (int32_t in = 0; in < kEmbeddingDim; ++in) {
          value += lda[static_cast<size_t>(in) * kPldaDim + out] *
                   centered[in] * first_scale;
        }
        xvec[out] = value;
        xvec_norm += value * value;
      }
      xvec_norm = std::sqrt(std::max(xvec_norm, 1e-20F));
      const float second_scale = std::sqrt(static_cast<float>(kPldaDim)) / xvec_norm;
      for (int32_t out = 0; out < kPldaDim; ++out) {
        float value = 0.0F;
        for (int32_t in = 0; in < kPldaDim; ++in) {
          value += transform[static_cast<size_t>(out) * kPldaDim + in] *
                   (xvec[in] * second_scale - mu[in]);
        }
        result[static_cast<size_t>(row) * kPldaDim + out] = value;
      }
    }
    return result;
  }
};

std::mutex g_mutex;
std::shared_ptr<PldaParameters> g_parameters;

struct LinkNode {
  int32_t left = -1;
  int32_t right = -1;
  int32_t size = 1;
  float distance = 0.0F;
  float max_distance = 0.0F;
  std::vector<float> centroid;
};

float SquaredDistance(const std::vector<float>& left,
                      const std::vector<float>& right) {
  float result = 0.0F;
  for (size_t d = 0; d < left.size(); ++d) {
    const float delta = left[d] - right[d];
    result += delta * delta;
  }
  return result;
}

std::vector<int32_t> KmeansLabels(const std::vector<float>& embeddings,
                                  int32_t rows, int32_t clusters) {
  std::vector<float> normalized(embeddings.size());
  for (int32_t row = 0; row < rows; ++row) {
    float norm = 0.0F;
    for (int32_t d = 0; d < kEmbeddingDim; ++d) {
      const float value = embeddings[static_cast<size_t>(row) * kEmbeddingDim + d];
      norm += value * value;
    }
    norm = std::sqrt(std::max(norm, 1e-20F));
    for (int32_t d = 0; d < kEmbeddingDim; ++d) {
      normalized[static_cast<size_t>(row) * kEmbeddingDim + d] =
          embeddings[static_cast<size_t>(row) * kEmbeddingDim + d] / norm;
    }
  }
  std::vector<float> centers(static_cast<size_t>(clusters) * kEmbeddingDim);
  // Deterministic farthest-point initialization is equivalent in purpose to
  // Community-1's fixed-seed KMeans initialization and avoids runtime RNG.
  std::vector<int32_t> seeds;
  seeds.push_back(0);
  while (static_cast<int32_t>(seeds.size()) < clusters) {
    int32_t best = 0;
    float best_distance = -1.0F;
    for (int32_t row = 0; row < rows; ++row) {
      float nearest = std::numeric_limits<float>::infinity();
      for (int32_t seed : seeds) {
        float distance = 0.0F;
        for (int32_t d = 0; d < kEmbeddingDim; ++d) {
          const float delta = normalized[static_cast<size_t>(row) * kEmbeddingDim + d] -
              normalized[static_cast<size_t>(seed) * kEmbeddingDim + d];
          distance += delta * delta;
        }
        nearest = std::min(nearest, distance);
      }
      if (nearest > best_distance) {
        best_distance = nearest;
        best = row;
      }
    }
    seeds.push_back(best);
  }
  for (int32_t cluster = 0; cluster < clusters; ++cluster) {
    std::copy_n(normalized.begin() + static_cast<size_t>(seeds[cluster]) * kEmbeddingDim,
                kEmbeddingDim, centers.begin() + static_cast<size_t>(cluster) * kEmbeddingDim);
  }
  std::vector<int32_t> labels(rows, 0);
  for (int32_t iteration = 0; iteration < 50; ++iteration) {
    bool changed = false;
    for (int32_t row = 0; row < rows; ++row) {
      int32_t best = 0;
      float best_score = std::numeric_limits<float>::infinity();
      for (int32_t cluster = 0; cluster < clusters; ++cluster) {
        float distance = 0.0F;
        for (int32_t d = 0; d < kEmbeddingDim; ++d) {
          const float delta = normalized[static_cast<size_t>(row) * kEmbeddingDim + d] -
              centers[static_cast<size_t>(cluster) * kEmbeddingDim + d];
          distance += delta * delta;
        }
        if (distance < best_score) { best_score = distance; best = cluster; }
      }
      if (labels[row] != best) { labels[row] = best; changed = true; }
    }
    std::fill(centers.begin(), centers.end(), 0.0F);
    std::vector<int32_t> counts(clusters, 0);
    for (int32_t row = 0; row < rows; ++row) {
      const int32_t cluster = labels[row];
      ++counts[cluster];
      for (int32_t d = 0; d < kEmbeddingDim; ++d)
        centers[static_cast<size_t>(cluster) * kEmbeddingDim + d] +=
            normalized[static_cast<size_t>(row) * kEmbeddingDim + d];
    }
    for (int32_t cluster = 0; cluster < clusters; ++cluster) {
      if (counts[cluster] == 0) continue;
      float norm = 0.0F;
      for (int32_t d = 0; d < kEmbeddingDim; ++d) {
        centers[static_cast<size_t>(cluster) * kEmbeddingDim + d] /= counts[cluster];
        norm += centers[static_cast<size_t>(cluster) * kEmbeddingDim + d] *
            centers[static_cast<size_t>(cluster) * kEmbeddingDim + d];
      }
      norm = std::sqrt(std::max(norm, 1e-20F));
      for (int32_t d = 0; d < kEmbeddingDim; ++d)
        centers[static_cast<size_t>(cluster) * kEmbeddingDim + d] /= norm;
    }
    if (!changed) break;
  }
  return labels;
}

void AssignFlatCluster(const std::vector<LinkNode>& nodes, int32_t node,
                       float threshold, int32_t* next_label,
                       std::vector<int32_t>* labels) {
  const LinkNode& value = nodes[node];
  if (node < static_cast<int32_t>(labels->size())) {
    (*labels)[node] = (*next_label)++;
    return;
  }
  if (value.max_distance <= threshold) {
    std::vector<int32_t> stack{node};
    const int32_t label = (*next_label)++;
    while (!stack.empty()) {
      const int32_t current = stack.back();
      stack.pop_back();
      if (current < static_cast<int32_t>(labels->size())) {
        (*labels)[current] = label;
      } else {
        stack.push_back(nodes[current].left);
        stack.push_back(nodes[current].right);
      }
    }
    return;
  }
  AssignFlatCluster(nodes, value.left, threshold, next_label, labels);
  AssignFlatCluster(nodes, value.right, threshold, next_label, labels);
}

std::vector<int32_t> CentroidAhc(const std::vector<float>& embeddings,
                                 int32_t rows) {
  if (rows <= 1) return std::vector<int32_t>(rows, 0);
  std::vector<LinkNode> nodes;
  nodes.reserve(rows * 2 - 1);
  std::vector<int32_t> active;
  active.reserve(rows);
  for (int32_t row = 0; row < rows; ++row) {
    LinkNode node;
    node.centroid.assign(embeddings.begin() + static_cast<size_t>(row) * kEmbeddingDim,
                         embeddings.begin() + static_cast<size_t>(row + 1) * kEmbeddingDim);
    float norm = 0.0F;
    for (float value : node.centroid) norm += value * value;
    norm = std::sqrt(std::max(norm, 1e-20F));
    for (float& value : node.centroid) value /= norm;
    nodes.push_back(std::move(node));
    active.push_back(row);
  }

  while (active.size() > 1) {
    size_t best_left = 0;
    size_t best_right = 1;
    float best_squared = std::numeric_limits<float>::infinity();
    for (size_t left = 0; left < active.size(); ++left) {
      for (size_t right = left + 1; right < active.size(); ++right) {
        const float distance = SquaredDistance(nodes[active[left]].centroid,
                                               nodes[active[right]].centroid);
        if (distance < best_squared) {
          best_squared = distance;
          best_left = left;
          best_right = right;
        }
      }
    }
    const int32_t left_id = active[best_left];
    const int32_t right_id = active[best_right];
    const LinkNode& left = nodes[left_id];
    const LinkNode& right = nodes[right_id];
    LinkNode merged;
    merged.left = left_id;
    merged.right = right_id;
    merged.size = left.size + right.size;
    merged.distance = std::sqrt(std::max(best_squared, 0.0F));
    merged.max_distance = std::max(merged.distance,
                                   std::max(left.max_distance, right.max_distance));
    merged.centroid.resize(kEmbeddingDim);
    for (int32_t d = 0; d < kEmbeddingDim; ++d) {
      merged.centroid[d] =
          (left.centroid[d] * left.size + right.centroid[d] * right.size) /
          merged.size;
    }
    nodes.push_back(std::move(merged));
    active[best_left] = static_cast<int32_t>(nodes.size() - 1);
    active.erase(active.begin() + best_right);
  }

  std::vector<int32_t> labels(rows, -1);
  int32_t next_label = 0;
  AssignFlatCluster(nodes, active.front(), kAhcThreshold, &next_label, &labels);
  return labels;
}

float LogSumExp(const std::vector<float>& values, size_t offset, int32_t count) {
  float maximum = -std::numeric_limits<float>::infinity();
  for (int32_t index = 0; index < count; ++index) {
    maximum = std::max(maximum, values[offset + index]);
  }
  float sum = 0.0F;
  for (int32_t index = 0; index < count; ++index) {
    sum += std::exp(values[offset + index] - maximum);
  }
  return maximum + std::log(std::max(sum, 1e-30F));
}

struct VbxResult {
  std::vector<float> responsibilities;
  std::vector<float> priors;
};

VbxResult RunVbx(const std::vector<int32_t>& ahc,
                 const std::vector<float>& features,
                 const std::vector<float>& phi, int32_t rows) {
  const int32_t speakers = *std::max_element(ahc.begin(), ahc.end()) + 1;
  const float high = std::exp(7.0F);
  const float denominator = high + speakers - 1;
  std::vector<float> gamma(static_cast<size_t>(rows) * speakers);
  for (int32_t row = 0; row < rows; ++row) {
    for (int32_t speaker = 0; speaker < speakers; ++speaker) {
      gamma[static_cast<size_t>(row) * speakers + speaker] =
          (ahc[row] == speaker ? high : 1.0F) / denominator;
    }
  }
  std::vector<float> priors(speakers, 1.0F / speakers);
  std::vector<float> rho(static_cast<size_t>(rows) * kPldaDim);
  std::vector<float> gaussian(rows);
  for (int32_t row = 0; row < rows; ++row) {
    float squared = 0.0F;
    for (int32_t d = 0; d < kPldaDim; ++d) {
      const float value = features[static_cast<size_t>(row) * kPldaDim + d];
      squared += value * value;
      rho[static_cast<size_t>(row) * kPldaDim + d] = value * std::sqrt(phi[d]);
    }
    gaussian[row] = -0.5F * (squared + kPldaDim * std::log(2.0F * 3.14159265358979323846F));
  }

  std::vector<float> inv_l(static_cast<size_t>(speakers) * kPldaDim);
  std::vector<float> alpha(static_cast<size_t>(speakers) * kPldaDim);
  std::vector<float> log_probability(static_cast<size_t>(rows) * speakers);
  float previous_elbo = -std::numeric_limits<float>::infinity();
  const float scale = kFa / kFb;
  for (int32_t iteration = 0; iteration < kMaxIters; ++iteration) {
    for (int32_t speaker = 0; speaker < speakers; ++speaker) {
      float count = 0.0F;
      for (int32_t row = 0; row < rows; ++row) {
        count += gamma[static_cast<size_t>(row) * speakers + speaker];
      }
      for (int32_t d = 0; d < kPldaDim; ++d) {
        float sufficient = 0.0F;
        for (int32_t row = 0; row < rows; ++row) {
          sufficient += gamma[static_cast<size_t>(row) * speakers + speaker] *
                        rho[static_cast<size_t>(row) * kPldaDim + d];
        }
        const size_t index = static_cast<size_t>(speaker) * kPldaDim + d;
        inv_l[index] = 1.0F / (1.0F + scale * count * phi[d]);
        alpha[index] = scale * inv_l[index] * sufficient;
      }
    }

    for (int32_t row = 0; row < rows; ++row) {
      for (int32_t speaker = 0; speaker < speakers; ++speaker) {
        float linear = 0.0F;
        float quadratic = 0.0F;
        for (int32_t d = 0; d < kPldaDim; ++d) {
          const size_t model = static_cast<size_t>(speaker) * kPldaDim + d;
          linear += rho[static_cast<size_t>(row) * kPldaDim + d] * alpha[model];
          quadratic += (inv_l[model] + alpha[model] * alpha[model]) * phi[d];
        }
        log_probability[static_cast<size_t>(row) * speakers + speaker] =
            kFa * (linear - 0.5F * quadratic + gaussian[row]) +
            std::log(priors[speaker] + 1e-8F);
      }
    }

    float log_likelihood = 0.0F;
    std::fill(priors.begin(), priors.end(), 0.0F);
    for (int32_t row = 0; row < rows; ++row) {
      const size_t offset = static_cast<size_t>(row) * speakers;
      const float normalizer = LogSumExp(log_probability, offset, speakers);
      log_likelihood += normalizer;
      for (int32_t speaker = 0; speaker < speakers; ++speaker) {
        const float value = std::exp(log_probability[offset + speaker] - normalizer);
        gamma[offset + speaker] = value;
        priors[speaker] += value;
      }
    }
    for (float& prior : priors) prior /= rows;

    float regularizer = 0.0F;
    for (size_t index = 0; index < inv_l.size(); ++index) {
      regularizer += std::log(inv_l[index]) - inv_l[index] -
                     alpha[index] * alpha[index] + 1.0F;
    }
    const float elbo = log_likelihood + kFb * 0.5F * regularizer;
    if (iteration > 0 && elbo - previous_elbo < 1e-4F) break;
    previous_elbo = elbo;
  }
  return {std::move(gamma), std::move(priors)};
}

void BestUniqueAssignment(const std::vector<float>& scores, int32_t rows,
                          int32_t columns, int32_t row, uint64_t used,
                          float score, std::vector<int32_t>* current,
                          float* best_score, std::vector<int32_t>* best) {
  if (row == rows) {
    if (score > *best_score) {
      *best_score = score;
      *best = *current;
    }
    return;
  }
  if (columns < rows) {
    (*current)[row] = -2;
    BestUniqueAssignment(scores, rows, columns, row + 1, used, score,
                         current, best_score, best);
  }
  for (int32_t column = 0; column < columns; ++column) {
    if (column < 64 && (used & (uint64_t{1} << column)) != 0) continue;
    (*current)[row] = column;
    BestUniqueAssignment(scores, rows, columns, row + 1,
                         column < 64 ? used | (uint64_t{1} << column) : used,
                         score + scores[static_cast<size_t>(row) * columns + column],
                         current, best_score, best);
  }
}

struct ClusterOutput {
  std::vector<int32_t> hard_clusters;
  int32_t speaker_count = 0;
  bool constraint_violated = false;
};

ClusterOutput Cluster(const PldaParameters& parameters,
                      const std::vector<float>& all_embeddings,
                      const std::vector<int32_t>& frame_masks,
                      int32_t chunks, int32_t min_speakers,
                      int32_t max_speakers) {
  const size_t expected_embeddings =
      static_cast<size_t>(chunks) * kLocalSpeakers * kEmbeddingDim;
  const size_t expected_masks = static_cast<size_t>(chunks) * kFrames;
  if (chunks <= 0 || all_embeddings.size() != expected_embeddings ||
      frame_masks.size() != expected_masks) {
    throw std::runtime_error(
        "invalid Community-1 clustering input shape: chunks=" +
        std::to_string(chunks) + ", embeddings=" +
        std::to_string(all_embeddings.size()) + ", expectedEmbeddings=" +
        std::to_string(expected_embeddings) + ", masks=" +
        std::to_string(frame_masks.size()) + ", expectedMasks=" +
        std::to_string(expected_masks));
  }

  std::vector<int32_t> train_indexes;
  std::vector<float> train_embeddings;
  for (int32_t chunk = 0; chunk < chunks; ++chunk) {
    int32_t clean_counts[kLocalSpeakers] = {0, 0, 0};
    for (int32_t frame = 0; frame < kFrames; ++frame) {
      const int32_t mask = frame_masks[static_cast<size_t>(chunk) * kFrames + frame];
      if (mask == 1) ++clean_counts[0];
      if (mask == 2) ++clean_counts[1];
      if (mask == 4) ++clean_counts[2];
    }
    for (int32_t local = 0; local < kLocalSpeakers; ++local) {
      const int32_t flat = chunk * kLocalSpeakers + local;
      const float* embedding = all_embeddings.data() +
                               static_cast<size_t>(flat) * kEmbeddingDim;
      bool valid = clean_counts[local] >= static_cast<int32_t>(std::ceil(0.2F * kFrames));
      for (int32_t d = 0; d < kEmbeddingDim && valid; ++d) valid = std::isfinite(embedding[d]);
      if (!valid) continue;
      train_indexes.push_back(flat);
      train_embeddings.insert(train_embeddings.end(), embedding, embedding + kEmbeddingDim);
    }
  }

  ClusterOutput output;
  output.hard_clusters.assign(static_cast<size_t>(chunks) * kLocalSpeakers, -2);
  if (train_indexes.empty()) return output;
  if (train_indexes.size() == 1) {
    output.speaker_count = 1;
    // With a single usable embedding the official pipeline cannot satisfy a
    // larger explicit minimum. Keep every active local channel together.
    for (int32_t chunk = 0; chunk < chunks; ++chunk) {
      for (int32_t local = 0; local < kLocalSpeakers; ++local) {
        bool active = false;
        for (int32_t frame = 0; frame < kFrames; ++frame) {
          const int32_t mask = frame_masks[static_cast<size_t>(chunk) * kFrames + frame];
          if (mask == (1 << local)) { active = true; break; }
        }
        const int32_t flat = chunk * kLocalSpeakers + local;
        const float* embedding = all_embeddings.data() +
            static_cast<size_t>(flat) * kEmbeddingDim;
        bool finite = true;
        for (int32_t d = 0; d < kEmbeddingDim && finite; ++d) finite = std::isfinite(embedding[d]);
        if (active && finite) output.hard_clusters[flat] = 0;
      }
    }
  } else {
    const int32_t rows = static_cast<int32_t>(train_indexes.size());
    const std::vector<int32_t> ahc = CentroidAhc(train_embeddings, rows);
    const std::vector<float> features = parameters.Transform(train_embeddings, rows);
    const VbxResult vbx = RunVbx(ahc, features, parameters.phi, rows);
    std::vector<int32_t> retained;
    for (int32_t speaker = 0; speaker < static_cast<int32_t>(vbx.priors.size()); ++speaker) {
      if (vbx.priors[speaker] > kPiFloor) retained.push_back(speaker);
    }
    const int32_t auto_speakers = static_cast<int32_t>(retained.size());
    int32_t requested_speakers = auto_speakers;
    if (min_speakers > 0 && requested_speakers < min_speakers) {
      requested_speakers = min_speakers;
    }
    if (max_speakers > 0 && requested_speakers > max_speakers) {
      requested_speakers = max_speakers;
    }
    // Community-1 switches to unconstrained KMeans whenever an explicit
    // speaker bound changes the automatically estimated number of clusters.
    const bool force_kmeans = requested_speakers != auto_speakers &&
                              requested_speakers > 0 && requested_speakers <= rows;
    output.speaker_count = force_kmeans ? requested_speakers : auto_speakers;
    if (output.speaker_count <= 0) return output;
    std::vector<int32_t> kmeans_labels;
    if (force_kmeans) kmeans_labels = KmeansLabels(train_embeddings, rows,
                                                   output.speaker_count);
    std::vector<float> centroids(static_cast<size_t>(output.speaker_count) * kEmbeddingDim);
    for (int32_t target = 0; target < output.speaker_count; ++target) {
      float weight = 0.0F;
      for (int32_t row = 0; row < rows; ++row) {
        const float responsibility = force_kmeans
            ? (kmeans_labels[row] == target ? 1.0F : 0.0F)
            : vbx.responsibilities[static_cast<size_t>(row) * vbx.priors.size() +
                                     retained[target]];
        weight += responsibility;
        for (int32_t d = 0; d < kEmbeddingDim; ++d) {
          centroids[static_cast<size_t>(target) * kEmbeddingDim + d] +=
              responsibility * train_embeddings[static_cast<size_t>(row) * kEmbeddingDim + d];
        }
      }
      for (int32_t d = 0; d < kEmbeddingDim; ++d) {
        centroids[static_cast<size_t>(target) * kEmbeddingDim + d] /= std::max(weight, 1e-20F);
      }
    }

    for (int32_t chunk = 0; chunk < chunks; ++chunk) {
      std::vector<float> scores(static_cast<size_t>(kLocalSpeakers) * output.speaker_count,
                                -1e30F);
      for (int32_t local = 0; local < kLocalSpeakers; ++local) {
        const float* embedding = all_embeddings.data() +
            static_cast<size_t>(chunk * kLocalSpeakers + local) * kEmbeddingDim;
        float embedding_norm = 0.0F;
        bool valid = true;
        for (int32_t d = 0; d < kEmbeddingDim; ++d) {
          valid = valid && std::isfinite(embedding[d]);
          embedding_norm += embedding[d] * embedding[d];
        }
        if (!valid || embedding_norm <= 0.0F) continue;
        embedding_norm = std::sqrt(embedding_norm);
        for (int32_t target = 0; target < output.speaker_count; ++target) {
          float dot = 0.0F;
          float centroid_norm = 0.0F;
          for (int32_t d = 0; d < kEmbeddingDim; ++d) {
            const float centroid = centroids[static_cast<size_t>(target) * kEmbeddingDim + d];
            dot += embedding[d] * centroid;
            centroid_norm += centroid * centroid;
          }
          scores[static_cast<size_t>(local) * output.speaker_count + target] =
              1.0F + dot / (embedding_norm * std::sqrt(std::max(centroid_norm, 1e-20F)));
        }
      }
      if (force_kmeans) {
        // constrained_assignment=False in pyannote's forced-KMeans path.
        for (int32_t local = 0; local < kLocalSpeakers; ++local) {
          int32_t best = -2;
          float best_score = -std::numeric_limits<float>::infinity();
          for (int32_t target = 0; target < output.speaker_count; ++target) {
            const float score = scores[static_cast<size_t>(local) * output.speaker_count + target];
            if (score > best_score) { best_score = score; best = target; }
          }
          output.hard_clusters[chunk * kLocalSpeakers + local] = best;
        }
      } else {
        std::vector<int32_t> current(kLocalSpeakers, -2);
        std::vector<int32_t> best(kLocalSpeakers, -2);
        float best_score = -std::numeric_limits<float>::infinity();
        BestUniqueAssignment(scores, kLocalSpeakers, output.speaker_count, 0, 0, 0.0F,
                             &current, &best_score, &best);
        for (int32_t local = 0; local < kLocalSpeakers; ++local) {
          output.hard_clusters[chunk * kLocalSpeakers + local] = best[local];
        }
      }
    }
  }

  output.constraint_violated =
      (min_speakers > 0 && output.speaker_count < min_speakers) ||
      (max_speakers > 0 && output.speaker_count > max_speakers);
  return output;
}

napi_value LoadParameters(napi_env env, napi_callback_info info) {
  size_t argc = 1;
  napi_value args[1] = {nullptr};
  napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
  try {
    if (argc != 1) throw std::runtime_error("Community-1 PLDA bytes required");
    auto parameters = PldaParameters::Parse(
        CopyTypedArray<uint8_t>(env, args[0], napi_uint8_array));
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      g_parameters = std::move(parameters);
    }
    napi_value value = nullptr;
    napi_get_undefined(env, &value);
    return value;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

struct ClusterContext {
  napi_deferred deferred = nullptr;
  napi_async_work work = nullptr;
  std::shared_ptr<PldaParameters> parameters;
  std::vector<float> embeddings;
  std::vector<int32_t> frame_masks;
  int32_t chunks = 0;
  int32_t min_speakers = 0;
  int32_t max_speakers = 0;
  ClusterOutput output;
  std::string error;
};

void ExecuteCluster(napi_env, void* data) {
  auto* context = static_cast<ClusterContext*>(data);
  try {
    context->output = Cluster(*context->parameters, context->embeddings,
                              context->frame_masks, context->chunks,
                              context->min_speakers, context->max_speakers);
  } catch (const std::exception& error) {
    context->error = error.what();
  } catch (...) {
    context->error = "unknown Community-1 clustering error";
  }
  context->parameters.reset();
  context->embeddings.clear();
  context->frame_masks.clear();
}

void CompleteCluster(napi_env env, napi_status status, void* data) {
  std::unique_ptr<ClusterContext> context(static_cast<ClusterContext*>(data));
  if (status != napi_ok && context->error.empty()) {
    context->error = "Community-1 clustering async work failed";
  }
  if (!context->error.empty()) {
    napi_value message = nullptr;
    napi_create_string_utf8(env, context->error.c_str(), NAPI_AUTO_LENGTH, &message);
    napi_reject_deferred(env, context->deferred, message);
    napi_delete_async_work(env, context->work);
    return;
  }
  napi_value result = nullptr;
  napi_create_object(env, &result);
  napi_value clusters = nullptr;
  napi_create_array_with_length(env, context->output.hard_clusters.size(), &clusters);
  for (uint32_t index = 0; index < context->output.hard_clusters.size(); ++index) {
    napi_value value = nullptr;
    napi_create_int32(env, context->output.hard_clusters[index], &value);
    napi_set_element(env, clusters, index, value);
  }
  napi_set_named_property(env, result, "hardClusters", clusters);
  napi_value speaker_count = nullptr;
  napi_create_int32(env, context->output.speaker_count, &speaker_count);
  napi_set_named_property(env, result, "speakerCount", speaker_count);
  napi_value violated = nullptr;
  napi_get_boolean(env, context->output.constraint_violated, &violated);
  napi_set_named_property(env, result, "constraintViolated", violated);
  napi_resolve_deferred(env, context->deferred, result);
  napi_delete_async_work(env, context->work);
}

napi_value ClusterAsync(napi_env env, napi_callback_info info) {
  size_t argc = 5;
  napi_value args[5] = {nullptr, nullptr, nullptr, nullptr, nullptr};
  napi_get_cb_info(env, info, &argc, args, nullptr, nullptr);
  try {
    if (argc < 3) throw std::runtime_error("Community-1 clustering arguments required");
    auto context = std::make_unique<ClusterContext>();
    context->embeddings = CopyTypedArray<float>(env, args[0], napi_float32_array);
    context->frame_masks = CopyTypedArray<int32_t>(env, args[1], napi_int32_array);
    napi_get_value_int32(env, args[2], &context->chunks);
    if (argc > 3) napi_get_value_int32(env, args[3], &context->min_speakers);
    if (argc > 4) napi_get_value_int32(env, args[4], &context->max_speakers);
    {
      std::lock_guard<std::mutex> lock(g_mutex);
      context->parameters = g_parameters;
    }
    if (context->parameters == nullptr) {
      throw std::runtime_error("Community-1 PLDA parameters are not loaded");
    }
    napi_value promise = nullptr;
    napi_status status = napi_create_promise(env, &context->deferred, &promise);
    if (status != napi_ok) throw std::runtime_error("failed to create Community-1 promise");
    napi_value name = nullptr;
    status = napi_create_string_utf8(env, "AmphionCommunity1Cluster", NAPI_AUTO_LENGTH, &name);
    if (status == napi_ok) {
      status = napi_create_async_work(env, nullptr, name, ExecuteCluster, CompleteCluster,
                                      context.get(), &context->work);
    }
    if (status == napi_ok) status = napi_queue_async_work(env, context->work);
    if (status != napi_ok) {
      if (context->work != nullptr) napi_delete_async_work(env, context->work);
      throw std::runtime_error("failed to queue Community-1 clustering work");
    }
    context.release();
    return promise;
  } catch (const std::exception& error) {
    napi_throw_error(env, nullptr, error.what());
    return nullptr;
  }
}

}  // namespace

void RegisterCommunity1Clusterer(napi_env env, napi_value exports) {
  napi_property_descriptor descriptors[] = {
      {"loadCommunity1Plda", nullptr, LoadParameters, nullptr, nullptr, nullptr,
       napi_default, nullptr},
      {"clusterCommunity1Async", nullptr, ClusterAsync, nullptr, nullptr, nullptr,
       napi_default, nullptr},
  };
  napi_define_properties(env, exports, sizeof(descriptors) / sizeof(descriptors[0]),
                         descriptors);
}
