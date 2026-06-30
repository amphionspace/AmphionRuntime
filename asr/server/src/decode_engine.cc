#include "decode_engine.h"

#include <algorithm>
#include <chrono>
#include <exception>
#include <iostream>
#include <unordered_set>
#include <utility>

#include "sherpa-onnx/c-api/c-api.h"

namespace asr_service {

struct DecodeEngine::Session {
    explicit Session(uint64_t session_id) : id(session_id) {}

    uint64_t id = 0;
    std::unique_ptr<sherpa_onnx::cxx::OnlineStream> stream;
    std::mutex stream_mutex;
    bool input_finished = false;
    bool alive = true;
};

DecodeEngine::DecodeEngine(std::shared_ptr<RecognizerFactory> factory,
                           int max_batch_size,
                           int loop_interval_ms)
    : factory_(std::move(factory)),
      owned_recognizer_(factory_ ? factory_->CreateRecognizer() : nullptr),
      recognizer_(owned_recognizer_ ? owned_recognizer_.get() : nullptr),
      max_batch_size_(std::max(1, max_batch_size)),
      loop_interval_ms_(std::max(1, loop_interval_ms)),
      worker_(&DecodeEngine::WorkerMain, this) {}

DecodeEngine::~DecodeEngine() {
    Stop();
}

std::shared_ptr<DecodeEngine::Session> DecodeEngine::CreateSession(
    const std::string &hotwords) {
    auto promise = std::make_shared<std::promise<std::shared_ptr<Session>>>();
    auto future = promise->get_future();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stop_requested_) {
            return nullptr;
        }
        Command cmd;
        cmd.type = CommandType::Create;
        cmd.hotwords = hotwords;
        cmd.create_promise = promise;
        commands_.push_back(std::move(cmd));
    }
    cv_.notify_one();
    return future.get();
}

DecodeEngine::StepResult DecodeEngine::Submit(
    const std::shared_ptr<Session> &session,
    std::vector<float> samples,
    int sample_rate,
    bool input_finished) {
    StepResult stopped;
    stopped.ok = false;
    stopped.error = "decode engine stopped";
    if (!session) {
        stopped.error = "decode session is null";
        return stopped;
    }

    auto promise = std::make_shared<std::promise<StepResult>>();
    auto future = promise->get_future();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stop_requested_) {
            return stopped;
        }
        Command cmd;
        cmd.type = CommandType::Submit;
        cmd.session = session;
        cmd.samples = std::move(samples);
        cmd.sample_rate = sample_rate;
        cmd.input_finished = input_finished;
        cmd.step_promise = promise;
        commands_.push_back(std::move(cmd));
    }
    cv_.notify_one();
    return future.get();
}

void DecodeEngine::DestroySession(const std::shared_ptr<Session> &session) {
    if (!session) {
        return;
    }
    auto promise = std::make_shared<std::promise<void>>();
    auto future = promise->get_future();
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stop_requested_) {
            return;
        }
        Command cmd;
        cmd.type = CommandType::Destroy;
        cmd.session = session;
        cmd.destroy_promise = promise;
        commands_.push_back(std::move(cmd));
    }
    cv_.notify_one();
    future.wait();
}

void DecodeEngine::Stop() {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (stop_requested_) {
            return;
        }
        stop_requested_ = true;
        Command cmd;
        cmd.type = CommandType::Stop;
        commands_.push_back(std::move(cmd));
    }
    cv_.notify_one();
    if (worker_.joinable()) {
        worker_.join();
    }
}

void DecodeEngine::WorkerMain() {
    while (true) {
        Command cmd;
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [this] { return !commands_.empty(); });
            cmd = std::move(commands_.front());
            commands_.pop_front();
        }

        if (cmd.type == CommandType::Stop) {
            break;
        }
        if (cmd.type == CommandType::Create) {
            ProcessCreate(cmd);
            continue;
        }
        if (cmd.type == CommandType::Destroy) {
            ProcessDestroy(cmd);
            continue;
        }

        std::vector<Command> submits;
        submits.push_back(std::move(cmd));
        const auto deadline = std::chrono::steady_clock::now() +
                              std::chrono::milliseconds(loop_interval_ms_);
        while (static_cast<int>(submits.size()) < max_batch_size_) {
            Command next;
            bool has_next = false;
            {
                std::unique_lock<std::mutex> lock(mutex_);
                if (commands_.empty()) {
                    cv_.wait_until(lock, deadline, [this] {
                        return !commands_.empty();
                    });
                }
                if (commands_.empty()) {
                    break;
                }
                next = std::move(commands_.front());
                commands_.pop_front();
                has_next = true;
            }
            if (!has_next) {
                break;
            }
            if (next.type == CommandType::Submit) {
                submits.push_back(std::move(next));
                continue;
            }
            if (next.type == CommandType::Create) {
                ProcessCreate(next);
            } else if (next.type == CommandType::Destroy) {
                ProcessDestroy(next);
            } else if (next.type == CommandType::Stop) {
                {
                    std::lock_guard<std::mutex> lock(mutex_);
                    commands_.push_front(std::move(next));
                }
                break;
            }
        }

        ProcessSubmits(std::move(submits));
    }

    FailRemainingCommands();
}

void DecodeEngine::ProcessCreate(Command &cmd) {
    std::shared_ptr<Session> session;
    try {
        if (recognizer_ && recognizer_->Get()) {
            session = std::make_shared<Session>(next_session_id_++);
            // sherpa-onnx only implements CreateStream(hotwords) for transducer
            // models. Use the plain stream path when there is no contextual biasing
            // so CTC/Paraformer models can share the same DecodeEngine.
            auto stream = cmd.hotwords.empty()
                              ? recognizer_->CreateStream()
                              : recognizer_->CreateStream(cmd.hotwords);
            session->stream = std::make_unique<sherpa_onnx::cxx::OnlineStream>(
                std::move(stream));
        }
    } catch (const std::exception &e) {
        std::cerr << "[decode_engine] CreateSession failed: " << e.what()
                  << std::endl;
        session.reset();
    }
    if (cmd.create_promise) {
        cmd.create_promise->set_value(session);
    }
}

void DecodeEngine::ProcessDestroy(Command &cmd) {
    if (cmd.session) {
        std::lock_guard<std::mutex> lock(cmd.session->stream_mutex);
        cmd.session->alive = false;
        cmd.session->stream.reset();
    }
    if (cmd.destroy_promise) {
        cmd.destroy_promise->set_value();
    }
}

void DecodeEngine::ProcessSubmits(std::vector<Command> submits) {
    std::vector<std::shared_ptr<Session>> touched;
    touched.reserve(submits.size());

    for (auto &cmd : submits) {
        auto session = cmd.session;
        try {
            if (!session) {
                continue;
            }
            std::lock_guard<std::mutex> lock(session->stream_mutex);
            if (!session || !session->alive || !session->stream) {
                continue;
            }
            touched.push_back(session);
            if (!cmd.samples.empty()) {
                session->stream->AcceptWaveform(
                    cmd.sample_rate, cmd.samples.data(),
                    static_cast<int32_t>(cmd.samples.size()));
            }
            if (cmd.input_finished && !session->input_finished) {
                session->stream->InputFinished();
                session->input_finished = true;
            }
        } catch (const std::exception &e) {
            if (cmd.step_promise) {
                StepResult r;
                r.ok = false;
                r.error = e.what();
                cmd.step_promise->set_value(std::move(r));
                cmd.step_promise.reset();
            }
        }
    }

    std::unordered_set<uint64_t> decoded_session_ids;
    try {
        while (true) {
            std::vector<std::shared_ptr<Session>> ready_sessions;
            ready_sessions.reserve(std::min<int>(max_batch_size_, touched.size()));
            for (const auto &session : touched) {
                if (!session) {
                    continue;
                }
                std::lock_guard<std::mutex> lock(session->stream_mutex);
                if (!session->alive || !session->stream) {
                    continue;
                }
                if (recognizer_->IsReady(session->stream.get())) {
                    ready_sessions.push_back(session);
                    if (static_cast<int>(ready_sessions.size()) >= max_batch_size_) {
                        break;
                    }
                }
            }
            if (ready_sessions.empty()) {
                break;
            }
            if (ready_sessions.size() == 1) {
                auto &session = ready_sessions.front();
                std::lock_guard<std::mutex> lock(session->stream_mutex);
                if (session->alive && session->stream) {
                    recognizer_->Decode(session->stream.get());
                    decoded_session_ids.insert(session->id);
                }
            } else {
                std::vector<const SherpaOnnxOnlineStream *> raw_streams;
                raw_streams.reserve(ready_sessions.size());
                std::vector<std::unique_lock<std::mutex>> locks;
                locks.reserve(ready_sessions.size());
                for (const auto &session : ready_sessions) {
                    locks.emplace_back(session->stream_mutex);
                    if (session->alive && session->stream) {
                        raw_streams.push_back(session->stream->Get());
                    }
                }
                if (raw_streams.empty()) {
                    continue;
                }
                SherpaOnnxDecodeMultipleOnlineStreams(
                    recognizer_->Get(), raw_streams.data(),
                    static_cast<int32_t>(raw_streams.size()));
                for (const auto &session : ready_sessions) {
                    decoded_session_ids.insert(session->id);
                }
            }
        }
    } catch (const std::exception &e) {
        for (auto &cmd : submits) {
            if (cmd.step_promise) {
                StepResult r;
                r.ok = false;
                r.error = e.what();
                cmd.step_promise->set_value(std::move(r));
                cmd.step_promise.reset();
            }
        }
    }

    for (auto &cmd : submits) {
        if (!cmd.step_promise) {
            continue;
        }
        StepResult r;
        auto session = cmd.session;
        if (!session) {
            r.ok = false;
            r.error = "decode session is closed";
            cmd.step_promise->set_value(std::move(r));
            continue;
        }
        try {
            std::lock_guard<std::mutex> lock(session->stream_mutex);
            if (!session->alive || !session->stream) {
                r.ok = false;
                r.error = "decode session is closed";
                cmd.step_promise->set_value(std::move(r));
                continue;
            }
            if (!cmd.input_finished && !decoded_session_ids.count(session->id)) {
                cmd.step_promise->set_value(std::move(r));
                continue;
            }
            r.result = recognizer_->GetResult(session->stream.get());
            r.has_result = true;
            r.is_endpoint = recognizer_->IsEndpoint(session->stream.get());
            r.is_eof = cmd.input_finished;
            if (r.is_endpoint) {
                recognizer_->Reset(session->stream.get());
            }
        } catch (const std::exception &e) {
            r.ok = false;
            r.error = e.what();
        }
        cmd.step_promise->set_value(std::move(r));
    }
}

void DecodeEngine::FailRemainingCommands() {
    std::deque<Command> remaining;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        remaining.swap(commands_);
    }
    for (auto &cmd : remaining) {
        if (cmd.create_promise) {
            cmd.create_promise->set_value(nullptr);
        }
        if (cmd.step_promise) {
            StepResult r;
            r.ok = false;
            r.error = "decode engine stopped";
            cmd.step_promise->set_value(std::move(r));
        }
        if (cmd.destroy_promise) {
            cmd.destroy_promise->set_value();
        }
    }
}

}  // namespace asr_service
