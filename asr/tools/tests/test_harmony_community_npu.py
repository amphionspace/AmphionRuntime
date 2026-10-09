"""Extract the production Encoder; synthetic CAPI/ORT boundaries, no models/audio."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_community_diarization import run_community_session

ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'asr/harmony/sdk/src/main/cpp/community_diarization.cpp'
FIXTURE = Path(__file__).with_name('harmony_community_npu')

CASES = r'''
const std::vector<uint8_t> asset{1, 2, 3};
template<class F> void Rejected(F action) {
  bool threw = false;
  try { action(); } catch (const std::exception&) { threw = true; }
  Check(threw, "expected encoder rejection");
}
void DeviceCase(const std::string& mode) {
  if (mode == "hiai-first") state.devices = {{"HIAI_F"}, {"Kirin990"}};
  else if (mode == "kirin-first") state.devices = {{"Kirin990"}, {"HIAI_F"}};
  else if (mode == "mixed-case") state.devices = {{"HIAI_F"}, {"vendor_kIrIn_NPU"}};
  else if (mode == "explicit") state.devices = {{"Kirin990"}, {"HIAI_F"}};
  else if (mode == "only-hiai") state.devices = {{"HIAI_F"}};
  else if (mode == "non-accelerators") state.devices = {{"Kirin_CPU", OH_AI_NNRTDEVICE_CPU},
                                                        {"Kirin_GPU", OH_AI_NNRTDEVICE_GPU}};
  else if (mode == "missing") state.devices.clear();
  else if (mode == "null-list") state.null_descs = true;
  else if (mode == "null-entries") state.devices = {{"Kirin_null", OH_AI_NNRTDEVICE_ACCELERATOR, false, true},
                                                   {"", OH_AI_NNRTDEVICE_ACCELERATOR, true}, {"Kirin990"}};
  else if (mode == "unmatched") state.devices = {{"Kirin990"}, {"HIAI_F"}};
  else throw std::runtime_error("unknown device case");
  if (mode == "only-hiai" || mode == "non-accelerators" || mode == "missing" ||
      mode == "null-list" || mode == "unmatched") {
    Rejected([&] { Encoder encoder(asset, mode == "unmatched" ? "absent" : ""); });
    Check(state.built_name.empty() && state.cpu_builds == 0, "strict NPU used an unrequested backend");
  } else {
    Encoder encoder(asset, mode == "explicit" ? "hiai_f" : "");
    const std::string expected = mode == "explicit" ? "HIAI_F" :
                                 mode == "mixed-case" ? "vendor_kIrIn_NPU" : "Kirin990";
    Check(state.built_name == expected, "selected=" + state.built_name + " expected=" + expected);
    Check(encoder.backend() == "npu", "actual backend lost");
    Check(encoder.device() == expected, "actual device name lost");
  }
  ResourcesReleased();
}
void FailureCase(const std::string& stage) {
  state.fail = stage;
  Rejected([&] { Encoder encoder(stage == "empty-asset" ? std::vector<uint8_t>{} : asset, ""); });
  ResourcesReleased();
  Check(state.desc_frees == (stage == "empty-asset" ? 0 : 1), "descriptor cleanup count");
  Check(state.context_frees == (stage == "empty-asset" || stage == "enumerate" || stage == "context" ? 0 : 1),
        "context cleanup count");
  Check(state.device_frees == (stage == "empty-asset" || stage == "enumerate" || stage == "context" ||
                               stage == "device" ? 0 : 1), "device ownership cleanup count");
  Check(state.model_frees == (stage == "build" ? 1 : 0), "model cleanup count");
}
void SignatureCase(const std::string& when, const std::string& side, const std::string& fault) {
  auto& setting = side == "input" ? state.input_fault : state.output_fault;
  if (when == "build") {
    setting = fault;
    Rejected([&] { Encoder encoder(asset, ""); });
  } else {
    {
      Encoder encoder(asset, "");
      if (when == "pre-run") setting = fault;
      else state.predict_fault = fault;
      std::vector<float> features(Encoder::kFeatureCount, .25f);
      Rejected([&] { encoder.Run(features); });
      Check(state.cpu_builds == 0 && state.cpu_runs == 0, "predict/signature failure silently used CPU");
      Check(state.predict_calls == (when == "post-predict" ? 1 : 0), "wrong failure stage");
      Check(state.set_data_calls == 0, "runtime borrowed caller features");
    }
  }
  ResourcesReleased();
}
void PredictFailure() {
  {
    Encoder encoder(asset, "");
    state.fail = "predict";
    std::vector<float> features(Encoder::kFeatureCount, .5f);
    Rejected([&] { encoder.Run(features); });
    Check(state.data_reads == 0, "read output after failed predict");
    Check(state.cpu_builds == 0 && state.cpu_runs == 0, "predict failure fell back to CPU");
    state.fail.clear();
    auto* out = encoder.Run(features);
    Check(out[0] == .5f && state.predict_calls == 2, "predict failure poisoned next run");
  }
  ResourcesReleased();
}
void IndependentRuns() {
  {
    Encoder first(asset, ""), second(asset, "");
    std::vector<float> a(Encoder::kFeatureCount), b(Encoder::kFeatureCount);
    for (size_t i = 0; i < a.size(); ++i) { a[i] = i / 512.f; b[i] = -a[i] - .25f; }
    const auto original = a;
    float* first_values = first.Run(a);
    Check(state.input_address != a.data() && state.output_address != first_values,
          "encoder retained caller/runtime buffer");
    std::vector<float> snapshot(first_values, first_values + Encoder::kEncodedCount);
    float* second_values = second.Run(b);
    Check(first_values != second_values && state.input_address != b.data(), "lanes share borrowed buffers");
    Check(std::equal(snapshot.begin(), snapshot.end(), first_values), "another lane changed the first output");
    for (size_t i = 0; i < snapshot.size(); ++i) {
      Check(snapshot[i] == a[i % a.size()] + (i % 251) / 1024.f, "input copy lost a feature");
      Check(second_values[i] == b[i % b.size()] + (i % 251) / 1024.f, "second lane used stale input");
    }
    a.assign(a.size(), 7.f);
    auto* repeated = first.Run(a);
    Check(repeated[0] == 7.f && second_values[0] == b[0], "repeated Run reused another window/lane");
    Check(state.mutable_calls == 3 && state.set_data_calls == 0 && b[0] == -.25f, "input ownership changed");
    Check(original[1] == 1 / 512.f, "test input corrupted");
    for (float marker : {2.f, 9.f}) {
      std::vector<float> short_lived(Encoder::kFeatureCount, marker);
      Check(first.Run(short_lived)[0] == marker, "short-lived window lost");
    } // Caller buffers die before the encoder.
  }
  ResourcesReleased();
}
void MoveDestruct() {
  {
    std::vector<Encoder> lanes;
    lanes.reserve(1);
    Encoder original(asset, "");
    std::vector<float> features(Encoder::kFeatureCount, .125f);
    original.Run(features);
    lanes.push_back(std::move(original));
    lanes.emplace_back(asset, ""); // Moves the first encoder again.
    Check(lanes[0].Run(features)[0] == .125f && lanes[1].Run(features)[0] == .125f, "moved encoder unusable");
    Check(state.live_models == 2 && state.live_contexts == 2, "move duplicated or lost ownership");
  }
  ResourcesReleased();
  Check(state.model_frees == 2 && state.context_frees == 2 && state.device_frees == 2, "move double-free/leak");
}
void BackendPolicy(const std::string& policy, bool constructor_failure) {
  state.fail = constructor_failure ? "build" : "";
  if (policy == "npu" && constructor_failure) Rejected([&] { MakeEncoder(policy); });
  else {
    auto encoder = MakeEncoder(policy);
    Check(encoder.backend() == (policy == "cpu" || constructor_failure ? "cpu" : "npu"), "backend policy lost");
    Check(encoder.device() == (policy == "cpu" || constructor_failure ? "cpu" : "Kirin990"), "device diagnostic lost");
    std::vector<float> features(Encoder::kFeatureCount, .25f);
    if (!constructor_failure && policy != "cpu") {
      state.fail = "predict";
      Rejected([&] { encoder.Run(features); });
      Check(state.cpu_builds == 0, "auto fell back after construction");
    } else Check(encoder.Run(features)[0] == .25f, "CPU fallback failed");
  }
  ResourcesReleased();
  Check(state.cpu_builds == (policy == "cpu" || (policy == "auto" && constructor_failure) ? 1 : 0),
        "unrequested CPU construction");
}
void HonestLogs() {
  { Encoder encoder(asset, ""); }
  Check(state.fp16_calls == 0, "NNRt uses CPU/GPU-only FP16 switch");
  Check(!state.log_formats.empty(), "missing build diagnostic");
  bool built = false;
  for (const auto& log : state.log_formats) {
    Check(log.find("fp16=1") == std::string::npos, "log asserts unproved FP16 computation");
    built |= log.find("device=") != std::string::npos && log.find("build=") != std::string::npos;
  }
  Check(built, "actual device/build status not logged");
  ResourcesReleased();
}
int main(int argc, char** argv) {
  try {
    Check(argc >= 2, "missing case");
    const std::string group = argv[1];
    if (group == "device") DeviceCase(argv[2]);
    else if (group == "failure") FailureCase(argv[2]);
    else if (group == "signature") SignatureCase(argv[2], argv[3], argv[4]);
    else if (group == "predict") PredictFailure();
    else if (group == "independent") IndependentRuns();
    else if (group == "move") MoveDestruct();
    else if (group == "policy") BackendPolicy(argv[2], std::string(argv[3]) == "fail");
    else if (group == "logs") HonestLogs();
    else throw std::runtime_error("unknown test case");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
'''


class HarmonyCommunityNpuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            raise unittest.SkipTest('C++17 compiler unavailable')
        cls.compiler = compiler
        source = CPP.read_text()
        encoder = source[source.index('class Encoder {'):source.index('\n// Role work is optional;')]
        factory = source[source.index('    auto make_encoder ='):source.index('    if (feature.size()')]
        cls.program = '#include "encoder_stubs.h"\n' + encoder + '''
Encoder MakeEncoder(const std::string& encoder_backend) {
  Ort::Env env_; Ort::SessionOptions options;
  const std::vector<uint8_t> encoder{1, 2, 3}, encoder_mindir{1, 2, 3};
''' + factory + '''
  return make_encoder(options);
}
''' + CASES
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.source = Path(cls.temporary.name) / 'encoder.cpp'
        cls.binary = Path(cls.temporary.name) / 'encoder'
        cls.source.write_text(cls.program)
        result = subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(FIXTURE),
                                 str(cls.source), '-o', str(cls.binary)], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def run_case(self, *args):
        result = subprocess.run([str(self.binary), *args], capture_output=True, text=True,
                                timeout=5, cwd=self.temporary.name)
        self.assertEqual(result.returncode, 0, ' '.join(args) + ': ' + result.stdout + result.stderr)

    def test_default_kirin_selection_and_explicit_internal_match(self):
        for mode in ['hiai-first', 'kirin-first', 'mixed-case', 'explicit', 'only-hiai',
                     'non-accelerators', 'missing', 'null-list', 'null-entries', 'unmatched']:
            with self.subTest(mode=mode):
                self.run_case('device', mode)

    def test_failed_construction_releases_every_owned_capi_resource(self):
        for stage in ['empty-asset', 'enumerate', 'context', 'device', 'performance', 'attach', 'model', 'build']:
            with self.subTest(stage=stage):
                self.run_case('failure', stage)

    def test_build_checks_fp32_complete_shapes_counts_lists_and_bytes(self):
        for side in ['input', 'output']:
            for fault in ['dtype', 'shape', 'rank', 'dynamic', 'count', 'bytes', 'oversized-bytes',
                          'null-shape', 'null-list', 'null-handle', 'zero-tensors', 'extra-tensor']:
                with self.subTest(side=side, fault=fault):
                    self.run_case('signature', 'build', side, fault)

    def test_each_run_revalidates_signature_before_copy_or_predict(self):
        for side in ['input', 'output']:
            faults = ['dtype', 'shape', 'rank', 'dynamic', 'count', 'bytes', 'oversized-bytes',
                      'null-shape', 'null-list', 'null-handle', 'zero-tensors', 'extra-tensor']
            if side == 'input':
                faults.append('null-data')
            for fault in faults:
                with self.subTest(side=side, fault=fault):
                    self.run_case('signature', 'pre-run', side, fault)

    def test_predict_checks_returned_fp32_tensor_and_rejects_all_nonfinite_values(self):
        for fault in ['dtype', 'shape', 'rank', 'dynamic', 'count', 'bytes', 'oversized-bytes',
                      'null-shape', 'null-list', 'null-handle', 'zero-tensors', 'extra-tensor', 'null-data', 'nan', 'inf']:
            with self.subTest(fault=fault):
                self.run_case('signature', 'post-predict', 'output', fault)

    def test_predict_failure_is_not_cpu_fallback_and_next_run_recovers(self):
        self.run_case('predict')

    def test_repeated_runs_and_lanes_copy_independent_buffers_without_owning_caller(self):
        self.run_case('independent')

    def test_move_and_destruct_release_resources_once(self):
        self.run_case('move')

    def test_auto_fallback_only_at_construction_and_strict_npu_never_falls_back(self):
        for policy in ['cpu', 'npu', 'auto']:
            for outcome in ['fail', 'success']:
                with self.subTest(policy=policy, outcome=outcome):
                    self.run_case('policy', policy, outcome)

    def test_device_and_build_logs_do_not_claim_compute_precision(self):
        self.run_case('logs')

    def test_capi_definitions_compile_against_actual_standalone_clt_headers(self):
        clt = Path(os.environ.get('DEVECO_CLI_CLT_PATH', Path.home() / '.local/share/harmony/command-line-tools'))
        includes = clt / 'sdk/default/openharmony/native/sysroot/usr/include'
        if not (includes / 'mindspore/model.h').is_file():
            self.skipTest('standalone CLT MindSpore headers unavailable')
        local = Path(self.temporary.name) / 'clt-headers'
        local.mkdir()
        for name in ['mindspore', 'info']:
            (local / name).symlink_to(includes / name, target_is_directory=True)
        binary = Path(self.temporary.name) / 'encoder-clt'
        result = subprocess.run([self.compiler, '-std=c++17', '-O2', '-DCOMMUNITY_CLT_HEADERS',
                                 '-Wno-ignored-attributes', '-I', str(local), '-I', str(FIXTURE),
                                 str(self.source), '-o', str(binary)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary), 'independent'], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_window_object_exports_encoder_timing_device_without_changing_embedding(self):
        source = CPP.read_text()
        start = source.index('struct Window {')
        window = source[start:source.index('\n#ifndef __ANDROID__', start)]
        bridge = source[source.index('void StringProperty('):source.index('void Complete(')]
        program = r'''
#include "encoder_stubs.h"
#include <unordered_map>
using napi_env=void*;
struct JSValue { double number=0;std::string text;std::unordered_map<std::string,JSValue*> fields; };
using napi_value=JSValue*;
std::vector<std::unique_ptr<JSValue>> objects;
JSValue* NewValue() {objects.push_back(std::make_unique<JSValue>());return objects.back().get();}
int napi_create_object(napi_env,napi_value* out) {*out=NewValue();return 0;}
int napi_create_double(napi_env,double n,napi_value* out) {*out=NewValue();(*out)->number=n;return 0;}
int napi_create_string_utf8(napi_env,const char* text,size_t n,napi_value* out) {
  *out=NewValue();(*out)->text.assign(text,n);return 0;
}
int napi_set_named_property(napi_env,napi_value obj,const char* name,napi_value value) {
  obj->fields[name]=value;return 0;
}
void FloatProperty(napi_env,napi_value,const char*,const std::vector<float>&) {}
''' + window + bridge + r'''
int main() {
  Window window;window.encoder_ms=12.5;window.embedding_ms=39;
  window.encoder_backend="npu";window.encoder_device="Kirin990";
  auto* result=WindowObject(nullptr,window);
  Check(result->fields.at("encoderMs")->number==12.5,"encoderMs not exported");
  Check(result->fields.at("embeddingMs")->number==39,"embeddingMs changed meaning");
  Check(result->fields.at("encoderBackend")->text=="npu","encoderBackend not exported");
  Check(result->fields.at("encoderDevice")->text=="Kirin990","actual device not exported");
}
'''
        path = Path(self.temporary.name) / 'window.cpp'
        binary = Path(self.temporary.name) / 'window'
        path.write_text(program)
        result = subprocess.run([self.compiler, '-std=c++17', '-O2', '-I', str(FIXTURE),
                                 str(path), '-o', str(binary)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_session_diagnostics_forward_encoder_timing_device_and_legacy_defaults(self):
        run_community_session('''
          const events=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult(){},onFinished(){}},(event,fields)=>events.push({event,fields}));
          const first=window(0);first.result.encoderMs=12.5;
          first.result.encoderBackend='npu';first.result.encoderDevice='Kirin990';first.result.embeddingMs=39;
          s.onWindow(first);
          const current=events.find(e=>e.event==='DIARIZATION_COMMUNITY_WINDOW').fields;
          assert.equal(current.encoderMs,12.5);assert.equal(current.encoderDevice,'Kirin990');
          assert.equal(current.encoderBackend,'npu');assert.equal(current.embeddingMs,39);
          s.onWindow(window(1));
          const legacy=events.filter(e=>e.event==='DIARIZATION_COMMUNITY_WINDOW')[1].fields;
          assert.equal(legacy.encoderMs,0);assert.equal(legacy.encoderDevice,'cpu');
          assert.equal(legacy.encoderBackend,'cpu');assert.equal(legacy.embeddingMs,0);
          assert.equal(current.encoderDevice,'Kirin990');assert.equal(current.encoderMs,12.5);
        ''')
