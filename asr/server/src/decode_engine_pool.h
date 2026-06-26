#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "decode_engine.h"
#include "recognizer_factory.h"

namespace asr_service {

// 单进程内的 recognizer 池：持有 N 个独立 DecodeEngine（每个一个 OnlineRecognizer +
// 单 worker 线程 + 批量队列），进程内共享同一 CUDA context。
// 会话按“最少活跃会话”路由到某个分片并固定在该分片上；Submit/DestroySession 按分片 O(1) 转发。
// 这样把解码并行度从 1 个核扩到 N 个核，绕过单解码线程在 16 vCPU 上的串行瓶颈。
class DecodeEnginePool {
public:
    using StepResult = DecodeEngine::StepResult;

    // 会话句柄：记录所属分片，供后续 Submit/Destroy 路由。
    struct Session {
        int engine_index = -1;
        DecodeEngine *engine = nullptr;
        std::shared_ptr<DecodeEngine::Session> inner;
    };

    DecodeEnginePool(std::shared_ptr<RecognizerFactory> factory,
                     int num_workers,
                     int max_batch_size,
                     int loop_interval_ms);
    ~DecodeEnginePool();

    DecodeEnginePool(const DecodeEnginePool &) = delete;
    DecodeEnginePool &operator=(const DecodeEnginePool &) = delete;

    std::shared_ptr<Session> CreateSession(const std::string &hotwords);
    StepResult Submit(const std::shared_ptr<Session> &session,
                      std::vector<float> samples,
                      int sample_rate,
                      bool input_finished);
    void DestroySession(const std::shared_ptr<Session> &session);
    void Stop();

    int num_workers() const { return static_cast<int>(engines_.size()); }

private:
    int PickEngineLocked() const;  // 调用者需持有 mutex_

    std::vector<std::unique_ptr<DecodeEngine>> engines_;
    std::vector<int> loads_;  // 每分片活跃会话数，受 mutex_ 保护
    mutable std::mutex mutex_;
    bool stopped_ = false;
};

}  // namespace asr_service
