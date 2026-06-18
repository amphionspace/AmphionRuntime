import SwiftUI
import AVFoundation
import AmphionRuntime

/// 单页 SwiftUI Demo：按住按钮录音 → ASR 流式识别 → 实时刷新文本。
/// 与 Android Sample 行为等价，跨端 UX 体验保持一致。
struct ContentView: View {
    @StateObject private var vm = AsrViewModel()

    var body: some View {
        VStack(spacing: 16) {
            Text("AmphionRuntime iOS Sample")
                .font(.title2.bold())
                .padding(.top, 24)

            Text("model: \(vm.modelStatus)")
                .font(.caption)
                .foregroundColor(.secondary)

            ScrollView {
                Text(vm.partial.isEmpty ? "[partial]" : vm.partial)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundColor(.gray)
                Divider()
                ForEach(vm.finals.indices, id: \.self) { idx in
                    Text(vm.finals[idx])
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 4)
                }
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color(.secondarySystemBackground))
            .cornerRadius(8)

            Button(action: {}) {
                Text(vm.isRecording ? "Recording... release to stop" : "Press & hold to talk")
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(vm.isRecording ? Color.red : Color.blue)
                    .foregroundColor(.white)
                    .cornerRadius(8)
            }
            .simultaneousGesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in vm.startRecordingIfNeeded() }
                    .onEnded   { _ in vm.stopRecording() }
            )

            HStack {
                Button("Update Hotwords") { vm.updateHotwords() }
                Button("Clear Result") { vm.clearResult() }
            }
            .padding(.top, 4)

            if let err = vm.errorMessage {
                Text("Error: \(err)").foregroundColor(.red).font(.caption)
            }
            Spacer()
        }
        .padding(.horizontal)
        .onAppear { vm.bootstrap() }
    }
}

// MARK: - ViewModel

@MainActor
final class AsrViewModel: ObservableObject, AsrCallback {

    @Published var modelStatus: String = "(idle)"
    @Published var partial: String = ""
    @Published var finals: [String] = []
    @Published var isRecording: Bool = false
    @Published var errorMessage: String? = nil

    private var engine: AsrEngine?
    private var session: AsrSession?
    private let recorder = MicRecorder()
    private let modelManager = ModelManager()

    func bootstrap() {
        // 1) 模型查找：优先用 Documents/AsrModels/<model_id>/<version>/
        //    Sample 演示用 model_id = "demo"、version = "1.0.0"
        let modelDir = modelManager.localDir(modelId: "demo", version: "1.0.0")
        guard FileManager.default.fileExists(atPath: modelDir.appendingPathComponent("tokens.txt").path) else {
            modelStatus = "model not found at \(modelDir.lastPathComponent); please import via iTunes / Files"
            errorMessage = "请把模型目录 demo/1.0.0/ 放到 app Documents/AsrModels/ 下；详见 README"
            return
        }
        modelStatus = "loading from \(modelDir.lastPathComponent)..."
        do {
            let cfg = AsrConfig(modelDir: modelDir)
                .with(numThreads: 2)
                .with(enableEndpoint: true)
            let e = try AsrEngine(config: cfg)
            engine = e
            session = e.newSession(callback: self)
            modelStatus = "ready"
        } catch let err as AsrError {
            errorMessage = "engine init failed: \(err)"
            modelStatus = "failed"
        } catch {
            errorMessage = "engine init failed: \(error)"
            modelStatus = "failed"
        }
    }

    func startRecordingIfNeeded() {
        guard !isRecording, session != nil else { return }
        isRecording = true
        partial = ""
        recorder.start { [weak self] samples in
            guard let self = self else { return }
            self.session?.acceptPcm(samples, sampleRate: 16000)
        } onError: { [weak self] err in
            self?.errorMessage = "recorder error: \(err)"
        }
    }

    func stopRecording() {
        guard isRecording else { return }
        isRecording = false
        recorder.stop()
        session?.stop()
    }

    func updateHotwords() {
        session?.updateHotwords(["端到端", "语音识别", "浦东机场"], score: 1.5)
    }

    func clearResult() {
        partial = ""
        finals.removeAll()
    }

    // MARK: AsrCallback
    nonisolated func onPartial(result: AsrResult) {
        Task { @MainActor in self.partial = result.text }
    }
    nonisolated func onFinal(result: AsrResult) {
        Task { @MainActor in
            if !result.text.isEmpty { self.finals.append(result.text) }
            self.partial = ""
        }
    }
    nonisolated func onError(_ error: AsrError) {
        Task { @MainActor in self.errorMessage = error.description }
    }
}

// MARK: - Mic recorder

/// 简易麦克风采集；16 kHz / mono / float32。生产环境建议用 AVAudioEngine + AVAudioConverter
/// 拿原生 sample rate 再下采样，这里是 demo 复杂度。
final class MicRecorder {
    private let engine = AVAudioEngine()
    private let targetSampleRate: Double = 16000
    private var converter: AVAudioConverter?

    func start(onSamples: @escaping ([Float]) -> Void,
               onError: @escaping (Error) -> Void) {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.defaultToSpeaker])
            try session.setActive(true)
        } catch {
            onError(error); return
        }
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        let outputFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                                          sampleRate: targetSampleRate,
                                          channels: 1,
                                          interleaved: false)!
        converter = AVAudioConverter(from: inputFormat, to: outputFormat)
        input.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buf, _ in
            guard let self = self, let conv = self.converter else { return }
            let outBuf = AVAudioPCMBuffer(pcmFormat: outputFormat,
                                          frameCapacity: AVAudioFrameCount(outputFormat.sampleRate * Double(buf.frameLength) / inputFormat.sampleRate))!
            var err: NSError?
            conv.convert(to: outBuf, error: &err) { _, status in
                status.pointee = .haveData
                return buf
            }
            if let err = err { onError(err); return }
            guard let chans = outBuf.floatChannelData else { return }
            let n = Int(outBuf.frameLength)
            let arr = Array(UnsafeBufferPointer(start: chans[0], count: n))
            onSamples(arr)
        }
        do {
            try engine.start()
        } catch {
            onError(error)
        }
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }
}

// MARK: - Preview

struct ContentView_Previews: PreviewProvider {
    static var previews: some View { ContentView() }
}
