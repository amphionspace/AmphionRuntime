#pragma once

#include <condition_variable>
#include <cstdint>
#include <deque>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "recognizer_factory.h"
#include "sherpa-onnx/c-api/cxx-api.h"

namespace asr_service {

class DecodeEngine {
public:
    struct Session;

    struct StepResult {
        bool ok = true;
        bool has_result = false;
        bool is_endpoint = false;
        bool is_eof = false;
        std::string error;
        sherpa_onnx::cxx::OnlineRecognizerResult result;
    };

    DecodeEngine(std::shared_ptr<RecognizerFactory> factory,
                 int max_batch_size,
                 int loop_interval_ms);
    ~DecodeEngine();

    DecodeEngine(const DecodeEngine &) = delete;
    DecodeEngine &operator=(const DecodeEngine &) = delete;

    std::shared_ptr<Session> CreateSession(const std::string &hotwords);
    StepResult Submit(const std::shared_ptr<Session> &session,
                      std::vector<float> samples,
                      int sample_rate,
                      bool input_finished);
    void DestroySession(const std::shared_ptr<Session> &session);
    void Stop();

private:
    enum class CommandType {
        Create,
        Submit,
        Destroy,
        Stop,
    };

    struct Command {
        CommandType type = CommandType::Stop;
        std::shared_ptr<Session> session;
        std::string hotwords;
        std::vector<float> samples;
        int sample_rate = 0;
        bool input_finished = false;
        std::shared_ptr<std::promise<std::shared_ptr<Session>>> create_promise;
        std::shared_ptr<std::promise<StepResult>> step_promise;
        std::shared_ptr<std::promise<void>> destroy_promise;
    };

    void WorkerMain();
    void ProcessCreate(Command &cmd);
    void ProcessDestroy(Command &cmd);
    void ProcessSubmits(std::vector<Command> submits);
    void FailRemainingCommands();

    std::shared_ptr<RecognizerFactory> factory_;
    std::unique_ptr<sherpa_onnx::cxx::OnlineRecognizer> owned_recognizer_;
    sherpa_onnx::cxx::OnlineRecognizer *recognizer_ = nullptr;
    int max_batch_size_ = 1;
    int loop_interval_ms_ = 5;

    std::mutex mutex_;
    std::condition_variable cv_;
    std::deque<Command> commands_;
    bool stop_requested_ = false;
    std::thread worker_;
    uint64_t next_session_id_ = 1;
};

}  // namespace asr_service
