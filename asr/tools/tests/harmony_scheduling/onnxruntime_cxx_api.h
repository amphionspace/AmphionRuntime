#pragma once
#include <map>
#include <string>
struct OrtCustomHandleType {};
using OrtCustomThreadHandle = const OrtCustomHandleType *;
using OrtThreadWorkerFn = void (*)(void *);
using OrtCustomCreateThreadFn = OrtCustomThreadHandle (*)(void *, OrtThreadWorkerFn, void *);
using OrtCustomJoinThreadFn = void (*)(OrtCustomThreadHandle);
namespace Ort {
struct SessionOptions {
  std::map<std::string, std::string> entries;
  OrtCustomCreateThreadFn create = nullptr;
  OrtCustomJoinThreadFn join = nullptr;
  void *context = nullptr;
  void AddConfigEntry(const char *key, const char *value) { entries[key] = value; }
  void SetCustomCreateThreadFn(OrtCustomCreateThreadFn fn) { create = fn; }
  void SetCustomJoinThreadFn(OrtCustomJoinThreadFn fn) { join = fn; }
  void SetCustomThreadCreationOptions(void *ptr) { context = ptr; }
};
}
