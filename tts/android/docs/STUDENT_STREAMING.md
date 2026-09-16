# Student 10000: cached streaming decoder

This configuration uses the replacement checkpoint with SHA256
`9edc6d5204dd595e511cd181590a9fe53d731d2704ce6cacb36ea4af3f2051d0`.
The 173-token inventory and Vocos 24 kHz vocoder are unchanged. Inference noise
temperature remains 0. This is a different checkpoint from the whole-utterance
Student 10000 bundle; do not substitute it into the non-streaming exporter.

## Training and runtime contract

The checkpoint records two IntMeanFlow intervals `[0, 0.5, 1]`, KV-cache-aligned
distillation, 100-frame chunks, 20-frame decoder history and a three-frame
lookahead parameter. `mu_streaming=false`: text expansion and condition encoding
run over the complete text segment. Only decoder generation and audio delivery
are incremental; this is not an incremental-text-input API.

The training chunk loop strips the nominal lookahead before decoder evaluation.
The exported hidden graph already contains the whole-segment condition encoder,
so Android's condition graph is an identity with masking and its additional
lookahead is zero. The final decoder chunk includes the remainder, matching the
training helper: 199 frames form one chunk; 201 frames form chunks of 100 and 101.

The `intmeanflow_absolute_kv_v1` contract carries 29 state tensors for each of the
two solver steps: attention K/V, absolute attention offsets and convolution tails.
Each request/text segment starts with empty caches. Subsequent chunks evaluate
only new frames. Android must not fall back to the legacy window decoder or run
this trained model with a different number of steps. Uniform inference chunks
of at least 40 frames are accepted; first/steady-size changes and growth remain
unsupported. See `STUDENT_MATCHED_50.md` for the current export limitations and
variable-chunk validation. Unsupported overrides are rejected. The sample's chunk input is blank by default so the
model's value is used.

The ordinary legacy decoder-cache experiment remains disabled. This model's
explicit manifest contract enables its required cache path independently.

## Export and build

Use the matching training source with its actual Cython alignment extension
compiled, as described in [STUDENT_10000.md](STUDENT_10000.md). The seven core
inference/distillation source files used locally were hash-checked against the
training server's streaming-performance source at revision
`ff0b78f63eec37a76aae5299d488f9a0bd5e427f`.

```sh
python tts/tools/android/export_intmeanflow_streaming.py \
  --distill-source /path/to/LITs-distill-streaming-performance \
  --checkpoint /path/to/student_step_0010000.pt \
  --frontend-assets /path/to/original-frontend/0.1.0 \
  --vocos /path/to/vocos_vocoder.onnx \
  --output /path/to/student-streaming/0.1.0 --temperature 0

cd tts/android
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug \
  -PLITS_TTS_MODEL_ID=dingqiao_intmeanflow_student_0010000_streaming_vocos24k \
  -PLITS_TTS_MODEL_DIR=/path/to/student-streaming/0.1.0 \
  -PLITS_TTS_SAMPLE_APPLICATION_ID=com.lits.tts.studentdemo \
  '-PLITS_TTS_SAMPLE_LABEL=Lits TTS Student Streaming'
```

Supply the appropriate `AMPHION_LICENSE_PUBLIC_KEY` and device license. The model
files are external resources, not embedded in the APK or AAR.

## Validation

The exporter compares hidden outputs with PyTorch and runs the exported cached
solver against the training `student_trajectory_kv_cache` helper for 16, 99, 100,
101, 199, 200, 201, 350 and 431 frames, including both speakers. This checks the
first chunk, state carry, partial final chunks and multiple solver intervals.
At temperature 0 the maximum absolute mel error was below `1.3e-5`.

`IntMeanFlowStreamingContractTest` checks mandatory cache metadata, override
rejection and the trained partition rule. `StreamingStudentDeviceTest` uses the
public SDK to verify streaming callbacks, save audio and measure first packet
latency. With `playAudio=true`, it also verifies direct streaming playback through
the public SDK and waits for both synthesis and playback completion. Playback is
explicitly opt-in. Execution success is not a subjective quality guarantee.
