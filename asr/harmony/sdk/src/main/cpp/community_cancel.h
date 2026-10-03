#pragma once

#include <atomic>
#include <stdexcept>

namespace community {

// A small token shared by the native model and the CPU-only feature/cluster
// helpers. It deliberately has no ORT dependency so Android can include the
// same headers; the model bridge separately maps Cancel() to ORT RunOptions.
class CancellationToken {
 public:
  bool IsCancelled() const noexcept {
    return cancelled_.load(std::memory_order_acquire);
  }

  void Cancel() noexcept {
    cancelled_.store(true, std::memory_order_release);
  }

  void ThrowIfCancelled() const {
    if (IsCancelled()) throw std::runtime_error("Community operation cancelled");
  }

 private:
  std::atomic<bool> cancelled_{false};
};

inline void CheckCancellation(const CancellationToken* token) {
  if (token != nullptr) token->ThrowIfCancelled();
}

}  // namespace community
