#include "decode_engine_pool.h"

#include <algorithm>
#include <iostream>
#include <utility>

namespace asr_service {

DecodeEnginePool::DecodeEnginePool(std::shared_ptr<RecognizerFactory> factory,
                                   int num_workers,
                                   int max_batch_size,
                                   int loop_interval_ms) {
    const int n = std::max(1, num_workers);
    engines_.reserve(n);
    loads_.assign(n, 0);
    for (int i = 0; i < n; ++i) {
        engines_.push_back(std::make_unique<DecodeEngine>(
            factory, max_batch_size, loop_interval_ms));
        std::cerr << "[decode_pool] worker #" << i << " recognizer ready" << std::endl;
    }
    std::cerr << "[decode_pool] initialized workers=" << n
              << " max_batch_size=" << max_batch_size
              << " loop_interval_ms=" << loop_interval_ms << std::endl;
}

DecodeEnginePool::~DecodeEnginePool() {
    Stop();
}

int DecodeEnginePool::PickEngineLocked() const {
    int best = 0;
    int best_load = loads_[0];
    for (int i = 1; i < static_cast<int>(loads_.size()); ++i) {
        if (loads_[i] < best_load) {
            best_load = loads_[i];
            best = i;
        }
    }
    return best;
}

std::shared_ptr<DecodeEnginePool::Session> DecodeEnginePool::CreateSession(
    const std::string &hotwords) {
    int idx = -1;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stopped_ || engines_.empty()) {
            return nullptr;
        }
        idx = PickEngineLocked();
        ++loads_[idx];
    }

    // CreateSession 会阻塞等待该分片 worker，必须在锁外执行，避免串行化所有会话创建。
    auto inner = engines_[idx]->CreateSession(hotwords);
    if (!inner) {
        std::lock_guard<std::mutex> lock(mutex_);
        --loads_[idx];
        return nullptr;
    }

    auto session = std::make_shared<Session>();
    session->engine_index = idx;
    session->engine = engines_[idx].get();
    session->inner = std::move(inner);
    return session;
}

DecodeEnginePool::StepResult DecodeEnginePool::Submit(
    const std::shared_ptr<Session> &session,
    std::vector<float> samples,
    int sample_rate,
    bool input_finished) {
    StepResult r;
    if (!session || !session->engine || !session->inner) {
        r.ok = false;
        r.error = "decode session is null";
        return r;
    }
    return session->engine->Submit(session->inner, std::move(samples), sample_rate,
                                   input_finished);
}

void DecodeEnginePool::DestroySession(const std::shared_ptr<Session> &session) {
    if (!session || !session->engine) {
        return;
    }
    session->engine->DestroySession(session->inner);
    std::lock_guard<std::mutex> lock(mutex_);
    if (session->engine_index >= 0 &&
        session->engine_index < static_cast<int>(loads_.size()) &&
        loads_[session->engine_index] > 0) {
        --loads_[session->engine_index];
    }
}

void DecodeEnginePool::Stop() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stopped_) {
            return;
        }
        stopped_ = true;
    }
    for (auto &e : engines_) {
        if (e) {
            e->Stop();
        }
    }
}

}  // namespace asr_service
