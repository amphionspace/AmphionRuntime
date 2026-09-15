# IntMeanFlow Student 10000 · 24 kHz

This Android configuration runs `student_step_0010000.pt` as a non-streaming,
two-step IntMeanFlow model with grid `[0, 0.5, 1]`, a 173-token frontend and a
24 kHz Vocos vocoder. The Android runtime uses local native TN and external model
resources. The inference temperature for this delivery is **0**: the initial
Gaussian noise is multiplied by zero before the two model evaluations. This is
an ONNX model setting, not a playback volume or an AAR runtime parameter.

## Export and build

The exporter requires the matching LITs-distill source (validated revision
`d878405d1a2c10eef0aefe5eb3227ca1fd3de2eb`), the checkpoint, and the original
150-token frontend asset directory plus the matching Vocos ONNX. It converts
the Chinese token mapping to the 173-token training inventory and checks acoustic
ONNX/PyTorch parity using the exact same sampled noise. Vocos is copied, not
re-exported or independently validated by this script.

```sh
python tts/tools/android/export_intmeanflow_student.py \
  --distill-source /path/to/LITs-distill \
  --checkpoint /path/to/student_step_0010000.pt \
  --frontend-assets /path/to/original-frontend/0.1.0 \
  --vocos /path/to/vocos_vocoder.onnx \
  --output /path/to/student/0.1.0 --temperature 0

cd tts/android
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug \
  -PLITS_TTS_MODEL_ID=dingqiao_intmeanflow_student_0010000_vocos24k \
  -PLITS_TTS_MODEL_DIR=/path/to/student/0.1.0 \
  -PLITS_TTS_SAMPLE_APPLICATION_ID=com.lits.tts.studentdemo \
  '-PLITS_TTS_SAMPLE_LABEL=Lits TTS Student 10000'
```

Configure `AMPHION_LICENSE_PUBLIC_KEY` for the intended license issuer. Model
weights, device licenses, private keys and test audio are external delivery inputs;
they are not committed. An APK or AAR alone does not contain the acoustic model.
Changing temperature requires deploying the updated ONNX file together with its
matching manifest. The default build configuration still selects the existing
streaming model unless the model properties above are supplied.

## Frontend and sample behavior

- In `zh-en`, numeric-only text follows Chinese TN, including `1.` and `45.`;
  decimal input keeps its decimal reading. Explicit `en-US` uses English TN.
- The frontend prepends the training `<sil>` token when the inventory contains
  it. Legacy inventories without that token retain their previous IDs. This does
  not prepend 300 ms of silent audio.
- The debug sample reads externally provisioned models and license files from
  its private files directory. Debug device-SN injection is for the test carrier;
  production hosts must supply their actual device identity provider.

## Validation and limitations

At temperature 0, eight independent generations of the same English sentence
produced byte-identical PCM on the test phone. Ten varied samples were subsequently
generated and played, including numeric, Chinese, mixed and English text.
Execution completed for all ten; listening feedback still identified quality
issues in the final two English samples. Temperature 0 is a selected experimental
configuration, not a demonstrated fix for all English artifacts.

The JVM suite runs against the selected student asset directory. Nine obsolete
legacy pronunciation assertions have been removed; this is not full raw-text
pronunciation coverage for the new inventory.

`NumericUtteranceDeviceTest` checks native TN and public SDK synthesis;
`ZeroTemperaturePlaybackDeviceTest` records repeated generations;
`ZeroTemperatureSamplesDeviceTest` records ten varied samples. The latter two use
the SDK synthesizer and PCM player directly. Audible tests must be explicitly
requested and provisioned with a license, work directory and device serial.
The temporary student/teacher comparison test has been removed.
