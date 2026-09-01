import SwiftUI
import AVFoundation
import AmphionRuntime

/// 单页 SwiftUI Demo：通过 Android/Harmony 同名的鼎桥兼容 API 完成录音和流式识别。
struct ContentView: View {
    @StateObject private var vm = AsrViewModel()

    private let blue = Color(red: 46 / 255, green: 107 / 255, blue: 230 / 255)
    private let page = Color(red: 244 / 255, green: 247 / 255, blue: 252 / 255)

    var body: some View {
        ZStack {
            page.edgesIgnoringSafeArea(.all)
            ScrollView {
                VStack(spacing: 14) {
                    header
                    scenarioCard
                    capabilityCard
                    recognitionCard
                    actionCard
                    if let err = vm.errorMessage {
                        Text(err).font(.caption).foregroundColor(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.horizontal, 16).padding(.vertical, 12)
            }
        }
        .onAppear { vm.bootstrap() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Amphion 离线语音识别").font(.title2.bold())
                    Text("iOS · Dingqiao SDK").font(.caption).foregroundColor(.secondary)
                }
                Spacer()
                Image(systemName: "waveform.circle.fill").font(.system(size: 34)).foregroundColor(blue)
            }
            HStack(spacing: 7) {
                Circle().fill(vm.isRecording ? Color.red : (vm.isReady ? Color.green : Color.orange))
                    .frame(width: 9, height: 9)
                Text(vm.isRecording ? "● 正在识别" : vm.modelStatus)
                    .font(.subheadline.weight(.medium))
                Spacer()
                Text(vm.callbackSummary).font(.system(size: 10, design: .monospaced))
                    .foregroundColor(vm.lifecyclePassed ? .green : .secondary)
            }
        }
    }

    private var scenarioCard: some View {
        DemoCard(title: "客户场景", subtitle: vm.scenario.description) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(DemoScenario.allCases) { item in
                        Chip(title: item.title, selected: vm.scenario == item, accent: blue) {
                            vm.scenario = item
                        }
                    }
                }
            }
            Text("录音源").font(.caption.weight(.semibold)).foregroundColor(.secondary)
            HStack(spacing: 8) {
                ForEach(DemoAudioSource.allCases) { item in
                    Chip(title: item.title, selected: vm.audioSource == item, accent: blue) {
                        vm.audioSource = item
                    }
                }
            }
        }
    }

    private var capabilityCard: some View {
        DemoCard(title: "增强能力", subtitle: "配置与 Android / HarmonyOS 使用同名参数") {
            CapabilityToggle(title: "声纹校验", icon: "person.crop.circle.badge.checkmark",
                             isOn: $vm.voiceprintEnabled, enabled: vm.voiceprintRegistered,
                             status: vm.voiceprintCapabilityStatus)
            CapabilityToggle(title: "Speaker VAD", icon: "waveform.badge.person.crop",
                             isOn: $vm.speakerVadEnabled, enabled: vm.voiceprintRegistered,
                             status: vm.voiceprintRegistered ? "可用" : "需先录入声纹")
            CapabilityToggle(title: "说话人角色分离", icon: "person.2.wave.2",
                             isOn: $vm.diarizationEnabled, enabled: vm.diarizationAvailable,
                             status: vm.diarizationAvailable ? "可用" : "模型未就绪")
            CapabilityToggle(title: "警务文本增强", icon: "shield.lefthalf.filled",
                             isOn: $vm.policeEnabled, enabled: vm.policeAvailable,
                             status: vm.policeAvailable ? "可用" : "运行时未接入")
            HStack(spacing: 8) {
                CapabilityBadge(title: "ITN", available: vm.itnAvailable)
                CapabilityBadge(title: "自动标点", available: vm.punctuationAvailable)
                Spacer()
                Text("final：ITN → 标点").font(.caption2).foregroundColor(.secondary)
            }
            if vm.voiceprintAvailable {
                HStack(spacing: 10) {
                    Button(action: {
                        vm.voiceprintRecording ? vm.finishVoiceprintEnrollment() : vm.startVoiceprintEnrollment()
                    }) {
                        Label(vm.voiceprintRecording ? "结束并注册" :
                                (vm.voiceprintRegistered ? "重新录入" : "录制声纹"),
                              systemImage: vm.voiceprintRecording ? "stop.circle.fill" : "waveform.badge.plus")
                            .font(.subheadline.bold())
                    }
                    .disabled(vm.isRecording || vm.voiceprintRegistering ||
                              (vm.voiceprintRecording && vm.voiceprintDuration < 3))
                    if vm.voiceprintRecording {
                        Text(String(format: "%.1f / 8.0 秒", vm.voiceprintDuration))
                            .font(.caption.monospacedDigit()).foregroundColor(.red)
                    } else if vm.voiceprintRegistering {
                        ProgressView().controlSize(.small)
                        Text("正在生成声纹…").font(.caption).foregroundColor(.secondary)
                    } else if vm.voiceprintRegistered {
                        Button("删除") { vm.deleteVoiceprint() }
                            .font(.caption).foregroundColor(.red)
                    }
                    Spacer()
                }
                if vm.voiceprintRecording {
                    ProgressView(value: min(vm.voiceprintDuration, 8), total: 8)
                        .tint(vm.voiceprintDuration >= 3 ? Color.green : Color.orange)
                    Text(vm.voiceprintDuration < 3 ? "继续朗读，满 3 秒后可注册" : "样本时长合格，可结束注册；8 秒自动结束")
                        .font(.caption2).foregroundColor(vm.voiceprintDuration < 3 ? .orange : .green)
                }
            }
            if !vm.voiceprintAvailable || !vm.diarizationAvailable || !vm.policeAvailable {
                Text("灰色能力表示当前交付模型/运行时尚未就绪，不会静默降级为假成功。")
                    .font(.caption2).foregroundColor(.secondary)
            }
        }
    }

    private var recognitionCard: some View {
        DemoCard(title: "识别结果", subtitle: vm.isRecording ? "正在接收 16 kHz PCM" : "等待识别") {
            if vm.isRecording {
                HStack(spacing: 8) {
                    Circle().fill(Color.red).frame(width: 8, height: 8)
                    Text("● 正在识别 · 点击下方红色按钮结束").font(.subheadline.bold()).foregroundColor(.red)
                    Spacer()
                }
                .padding(10).background(Color.red.opacity(0.08)).cornerRadius(10)
            }
            Text(vm.partial.isEmpty ? "实时识别内容会显示在这里" : vm.partial)
                .foregroundColor(vm.partial.isEmpty ? .secondary : blue)
                .frame(maxWidth: .infinity, minHeight: 38, alignment: .topLeading)
            Divider()
            if vm.finals.isEmpty {
                Text("暂无最终结果").font(.subheadline).foregroundColor(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .topLeading)
            } else {
                ForEach(vm.finals.indices, id: \.self) { idx in
                    Text(vm.finals[idx]).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            if !vm.speakerSummary.isEmpty {
                Divider()
                HStack(spacing: 7) {
                    Image(systemName: "person.2.wave.2.fill").foregroundColor(blue)
                    Text(vm.speakerSummary).font(.caption).foregroundColor(.secondary)
                    Spacer()
                }
            }
            if vm.speakerVadEnabled {
                HStack(spacing: 7) {
                    Circle().fill(vm.speakerVadTargetActive == true ? Color.green : Color.orange)
                        .frame(width: 7, height: 7)
                    Text(vm.speakerVadStatus).font(.caption).foregroundColor(.secondary)
                    Spacer()
                }
            }
        }
    }

    private var actionCard: some View {
        VStack(spacing: 10) {
            Button(action: { vm.isRecording ? vm.stopRecording() : vm.startRecordingIfNeeded() }) {
                HStack(spacing: 10) {
                    Image(systemName: vm.isRecording ? "stop.fill" : "mic.fill")
                    Text(vm.isRecording ? "● 识别中 · 点击结束" : "开始识别").fontWeight(.bold)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 15)
                .background(vm.isRecording ? Color.red : blue).foregroundColor(.white).cornerRadius(14)
            }.disabled((!vm.isReady && !vm.isRecording) || vm.voiceprintRecording || vm.voiceprintRegistering)
            HStack {
                Button("取消") { vm.cancelRecording() }.disabled(!vm.isRecording)
                Spacer()
                Button("回放固定 WAV") { vm.runBundledSample() }.disabled(!vm.isReady || vm.isRecording)
                Spacer()
                Button("清空") { vm.clearResult() }
            }.font(.subheadline)
        }
    }
}

private struct DemoCard<Content: View>: View {
    let title: String; let subtitle: String; let content: Content
    init(title: String, subtitle: String, @ViewBuilder content: () -> Content) {
        self.title = title; self.subtitle = subtitle; self.content = content()
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.headline)
            Text(subtitle).font(.caption).foregroundColor(.secondary)
            content
        }.padding(14).background(Color.white).cornerRadius(16)
        .shadow(color: Color.black.opacity(0.05), radius: 8, y: 2)
    }
}

private struct Chip: View {
    let title: String; let selected: Bool; let accent: Color; let action: () -> Void
    var body: some View {
        Button(action: action) { Text(title).font(.caption.weight(.semibold)).padding(.horizontal, 12).padding(.vertical, 8) }
            .foregroundColor(selected ? .white : .primary)
            .background(selected ? accent : Color(red: 232/255, green: 237/255, blue: 246/255))
            .cornerRadius(18)
    }
}

private struct CapabilityToggle: View {
    let title: String; let icon: String; @Binding var isOn: Bool; let enabled: Bool; let status: String
    var body: some View {
        Toggle(isOn: $isOn) {
            HStack {
                Image(systemName: icon)
                Text(title)
                Text(status).font(.caption2.bold())
                    .padding(.horizontal, 7).padding(.vertical, 3)
                    .foregroundColor(enabled ? .green : .secondary)
                    .background((enabled ? Color.green : Color.gray).opacity(0.12))
                    .cornerRadius(8)
            }.font(.subheadline)
        }.disabled(!enabled)
    }
}

private struct CapabilityBadge: View {
    let title: String; let available: Bool
    var body: some View {
        Text("\(title) · \(available ? "可用" : "资源未就绪")")
            .font(.caption2.bold()).padding(.horizontal, 8).padding(.vertical, 4)
            .foregroundColor(available ? .green : .secondary)
            .background((available ? Color.green : Color.gray).opacity(0.12)).cornerRadius(8)
    }
}

enum DemoScenario: String, CaseIterable, Identifiable {
    case tapVad, pushToTalk, transcription, form, meeting
    var id: String { rawValue }
    var title: String {
        switch self { case .tapVad: return "点击+VAD"; case .pushToTalk: return "对讲"
        case .transcription: return "执法记录"; case .form: return "表单"; case .meeting: return "会议" }
    }
    var description: String {
        switch self { case .tapVad: return "短语音；5 秒未检测到起音会自动结束"; case .pushToTalk: return "手动开始和结束，不设置起音超时"
        case .transcription: return "长音频连续转写"; case .form: return "短字段快速录入"; case .meeting: return "长会话与角色分离" }
    }
}

enum DemoAudioSource: String, CaseIterable, Identifiable {
    case near, far, communication
    var id: String { rawValue }
    var title: String { switch self { case .near: return "近场"; case .far: return "远场"; case .communication: return "通话" } }
}

// MARK: - ViewModel

@MainActor
final class AsrViewModel: ObservableObject, RecognitionListener, PrepareRuntimeCallback,
                          VoiceprintRegisterCallback {

    @Published var modelStatus: String = "(idle)"
    @Published var partial: String = ""
    @Published var finals: [String] = []
    @Published var isRecording: Bool = false
    @Published var isReady: Bool = false
    @Published var errorMessage: String? = nil
    @Published var callbackSummary: String = "start=0 final=0 last=0 complete=0"
    @Published var lifecyclePassed: Bool = false
    @Published var scenario: DemoScenario = .pushToTalk
    @Published var audioSource: DemoAudioSource = .communication
    @Published var voiceprintEnabled = false
    @Published var speakerVadEnabled = false
    @Published var diarizationEnabled = false
    @Published var policeEnabled = false
    @Published var voiceprintAvailable = false
    @Published var voiceprintRegistered = false
    @Published var voiceprintRecording = false
    @Published var voiceprintRegistering = false
    @Published var voiceprintDuration: Double = 0
    @Published var diarizationAvailable = false
    @Published var policeAvailable = false
    @Published var itnAvailable = false
    @Published var punctuationAvailable = false
    @Published var speakerSummary = ""
    @Published var speakerVadStatus = "等待目标说话人判定"
    @Published var speakerVadTargetActive: Bool?

    private var engine: SpeechRecognitionEngine?
    private var sessionId: String?
    private var replayFrames: [Data] = []
    private var isReplaying = false
    private let recorder = MicRecorder()
    private let modelManager = ModelManager()
    private var voiceprintId: String?
    private var voiceprintPcm = Data()
    private var startCount = 0
    private var finalCount = 0
    private var lastCount = 0
    private var completeCount = 0

    func bootstrap() {
        // 1) 模型查找：优先用 Documents/AsrModels/<model_id>/<version>/
        //    Sample 演示用 model_id = "demo"、version = "1.0.0"
        let modelDir = modelManager.localDir(modelId: "demo", version: "1.0.0")
        guard FileManager.default.fileExists(atPath: modelDir.appendingPathComponent("tokens.txt").path) else {
            modelStatus = "model not found at \(modelDir.lastPathComponent); please import via iTunes / Files"
            errorMessage = "请把模型目录 demo/1.0.0/ 放到 app Documents/AsrModels/ 下；详见 README"
            return
        }
        modelStatus = "preparing from \(modelDir.lastPathComponent)..."
        do {
            let workPath = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("AmphionRuntime", isDirectory: true)
            try SpeechRecognizeSdk.shared.setWorkPath(workPath)
            SpeechRecognizeSdk.shared.setModelDirectory(modelDir)
            SpeechRecognizeSdk.shared.setAuxiliaryModelDirectory(
                modelManager.rootDir.appendingPathComponent("shared", isDirectory: true)
            )
            voiceprintAvailable = SpeechRecognizeSdk.shared.isVoiceprintAvailable()
            diarizationAvailable = SpeechRecognizeSdk.shared.isSpeakerDiarizationAvailable()
            let capabilities = SpeechRecognizeSdk.shared.runtimeCapabilities()
            itnAvailable = capabilities.inverseTextNormalization
            punctuationAvailable = capabilities.punctuation
            policeAvailable = capabilities.policeEnhancement
            if let stored = UserDefaults.standard.string(forKey: "amphion.demo.voiceprintId"),
               SpeechRecognizeSdk.shared.hasVoiceprint(stored) {
                voiceprintId = stored
                voiceprintRegistered = true
            } else {
                UserDefaults.standard.removeObject(forKey: "amphion.demo.voiceprintId")
            }
            SpeechRecognizeSdk.shared.prepareRuntime(callback: self)
        } catch {
            errorMessage = "prepare runtime failed: \(error)"
            modelStatus = "failed"
        }
    }

    func startRecordingIfNeeded() {
        guard !isRecording, let engine else { return }
        let id = UUID().uuidString
        sessionId = id
        isRecording = true
        partial = ""
        speakerSummary = ""
        speakerVadStatus = "等待目标说话人判定"
        speakerVadTargetActive = nil
        modelStatus = "starting"
        engine.startListening(
            StartParams(
                sessionId: id,
                extraParams: sessionExtraParams,
                speakerDiarization: diarizationEnabled ? SpeakerDiarizationConfig() : nil
            )
        )
        recorder.start(source: audioSource) { [weak self, weak engine] frame in
            guard let self, let engine else { return }
            Task { @MainActor in
                guard self.sessionId == id, self.isRecording else { return }
                engine.writeAudio(sessionId: id, audio: frame)
            }
        } onError: { [weak self] err in
            Task { @MainActor in self?.handleFailure("recorder error: \(err)") }
        }
    }

    private var sessionExtraParams: [String: Any] {
        let longForm = scenario == .transcription || scenario == .meeting
        var values: [String: Any] = [
            "recognizerMode": longForm ? "long" : "short",
            "enableContinuousRecognition": longForm,
            "enablePartialResult": true,
            "vadEnd": scenario == .pushToTalk ? 10_000 : (longForm ? 2_000 : 1_400),
            "enablePoliceEnhancement": policeEnabled,
            "enableVoiceprintVerification": voiceprintEnabled,
            "enableSpeakerVad": speakerVadEnabled,
        ]
        if scenario == .tapVad { values["vadBegin"] = 5_000 }
        if let voiceprintId, voiceprintEnabled || speakerVadEnabled {
            values["voiceprintIds"] = [voiceprintId]
        }
        return values
    }

    var voiceprintCapabilityStatus: String {
        if !voiceprintAvailable { return "模型未就绪" }
        if voiceprintRegistering { return "注册中" }
        return voiceprintRegistered ? "已注册" : "待录入"
    }

    func startVoiceprintEnrollment() {
        guard voiceprintAvailable, !isRecording, !voiceprintRegistering else { return }
        errorMessage = nil
        voiceprintPcm.removeAll(keepingCapacity: true)
        voiceprintDuration = 0
        voiceprintRecording = true
        modelStatus = "录制声纹中"
        recorder.start(source: audioSource) { [weak self] frame in
            Task { @MainActor in
                guard let self, self.voiceprintRecording else { return }
                self.voiceprintPcm.append(frame)
                self.voiceprintDuration = Double(self.voiceprintPcm.count) / 2 / 16_000
                if self.voiceprintDuration >= 8 { self.finishVoiceprintEnrollment() }
            }
        } onError: { [weak self] error in
            Task { @MainActor in self?.failVoiceprintEnrollment("声纹录音失败：\(error)") }
        }
    }

    func finishVoiceprintEnrollment() {
        guard voiceprintRecording else { return }
        guard voiceprintDuration >= 3 else { return }
        recorder.stop()
        voiceprintRecording = false
        voiceprintRegistering = true
        modelStatus = "正在注册声纹"
        do {
            let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("AmphionRuntime/voiceprint-samples", isDirectory: true)
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            let path = dir.appendingPathComponent("enroll-\(UUID().uuidString).pcm")
            try voiceprintPcm.write(to: path, options: .atomic)
            SpeechRecognizeSdk.shared.registerVoiceprint(
                VoiceprintRegisterParams(samplePaths: [path.path]), callback: self
            )
        } catch {
            failVoiceprintEnrollment("保存声纹样本失败：\(error)")
        }
    }

    func deleteVoiceprint() {
        guard let voiceprintId else { return }
        do {
            _ = try SpeechRecognizeSdk.shared.deleteVoiceprint(voiceprintId)
            self.voiceprintId = nil
            voiceprintRegistered = false
            voiceprintEnabled = false
            speakerVadEnabled = false
            UserDefaults.standard.removeObject(forKey: "amphion.demo.voiceprintId")
        } catch {
            errorMessage = "删除声纹失败：\(error)"
        }
    }

    private func failVoiceprintEnrollment(_ message: String) {
        recorder.stop()
        voiceprintRecording = false
        voiceprintRegistering = false
        voiceprintPcm.removeAll(keepingCapacity: true)
        modelStatus = isReady ? "ready" : "failed"
        errorMessage = message
    }

    func runBundledSample() {
        guard !isRecording, let engine else { return }
        guard let url = Bundle.main.url(forResource: "001_recognize", withExtension: "wav") else {
            handleFailure("bundled WAV is missing")
            return
        }
        do {
            replayFrames = try WavFixture.frames(from: url)
        } catch {
            handleFailure("invalid bundled WAV: \(error)")
            return
        }
        let id = "fixture_\(UUID().uuidString.replacingOccurrences(of: "-", with: "_"))"
        sessionId = id
        isRecording = true
        isReplaying = true
        resetCallbackCounts()
        partial = ""
        speakerSummary = ""
        speakerVadStatus = "等待目标说话人判定"
        speakerVadTargetActive = nil
        modelStatus = "starting fixture"
        engine.startListening(
            StartParams(
                sessionId: id,
                extraParams: sessionExtraParams,
                speakerDiarization: diarizationEnabled ? SpeakerDiarizationConfig() : nil
            )
        )
    }

    func stopRecording() {
        guard isRecording, let id = sessionId else { return }
        isRecording = false
        recorder.stop()
        modelStatus = "finishing"
        engine?.finish(sessionId: id)
    }

    func cancelRecording() {
        guard let id = sessionId else { return }
        recorder.stop()
        engine?.cancel(sessionId: id)
        sessionId = nil
        isRecording = false
        isReplaying = false
        replayFrames.removeAll(keepingCapacity: true)
        partial = ""
        modelStatus = "ready"
    }

    func clearResult() {
        partial = ""
        finals.removeAll()
        speakerSummary = ""
        speakerVadStatus = "等待目标说话人判定"
        speakerVadTargetActive = nil
    }

    // MARK: Dingqiao runtime / recognition callbacks

    nonisolated func onReady() {
        do {
            let params = CreateEngineParams(
                language: "zh-CN",
                extraParams: [
                    "recognizerMode": "short",
                    "sysGeneralLexicon": ["端到端", "语音识别", "浦东机场"],
                ]
            )
            let created = try SpeechRecognizeSdk.shared.createEngine(params)
            created.setListener(self)
            Task { @MainActor in
                self.engine = created
                self.modelStatus = "ready"
                self.isReady = true
            }
        } catch {
            Task { @MainActor in self.handleFailure("create engine failed: \(error)") }
        }
    }

    nonisolated func onError(errorCode: Int, errorMessage: String) {
        Task { @MainActor in
            if self.voiceprintRegistering {
                self.failVoiceprintEnrollment("声纹注册失败 \(errorCode)：\(errorMessage)")
            } else {
                self.handleFailure("\(errorCode): \(errorMessage)")
            }
        }
    }

    nonisolated func onResult(result: VoiceprintRegisterResult) {
        Task { @MainActor in
            guard result.status == 0, let id = result.voiceprintId.keys.first else {
                self.failVoiceprintEnrollment("声纹注册失败：\(result.message)")
                return
            }
            self.voiceprintId = id
            self.voiceprintRegistered = true
            self.voiceprintRegistering = false
            self.voiceprintPcm.removeAll(keepingCapacity: true)
            self.modelStatus = "ready"
            UserDefaults.standard.set(id, forKey: "amphion.demo.voiceprintId")
        }
    }

    nonisolated func onStart(sessionId: String, eventMessage: String) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            self.startCount += 1
            self.publishCallbackSummary()
            self.modelStatus = self.isReplaying ? "replaying fixture" : "recording"
            guard self.isReplaying, let engine = self.engine else { return }
            let frames = self.replayFrames
            Task.detached {
                frames.forEach { engine.writeAudio(sessionId: sessionId, audio: $0) }
                engine.finish(sessionId: sessionId)
            }
        }
    }

    nonisolated func onEvent(sessionId: String, eventCode: Int, eventMessage: String) {
        guard eventCode == DingqiaoEventCode.speakerVadChanged else { return }
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            let active = eventMessage == "target speaker active"
            self.speakerVadTargetActive = active
            self.speakerVadStatus = active ? "目标说话人正在讲话" : "当前不是目标说话人"
        }
    }

    nonisolated func onResult(sessionId: String, result: SpeechRecognitionResult) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            if result.isFinal {
                self.finalCount += 1
                if result.isLast { self.lastCount += 1 }
                self.publishCallbackSummary()
                if !result.result.isEmpty { self.finals.append(result.result) }
                self.partial = ""
            } else {
                self.partial = result.result
            }
        }
    }

    nonisolated func onComplete(sessionId: String, eventMessage: String) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            self.completeCount += 1
            self.lifecyclePassed = self.startCount == 1 && self.lastCount == 1 && self.completeCount == 1
            self.publishCallbackSummary()
            self.recorder.stop()
            self.sessionId = nil
            self.isRecording = false
            self.isReplaying = false
            self.replayFrames.removeAll(keepingCapacity: true)
            self.modelStatus = "ready"
        }
    }

    nonisolated func onSpeakerDiarizationUpdate(
        sessionId: String,
        update: SpeakerDiarizationUpdate
    ) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            self.speakerSummary = "角色更新：说话人 \(update.speakerIndex + 1)"
        }
    }

    nonisolated func onSpeakerDiarizationResult(
        sessionId: String,
        result: SpeakerDiarizationResult
    ) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            if result.degraded {
                self.speakerSummary = "角色分离降级：\(result.degradedReason.rawValue)"
            } else {
                self.speakerSummary = "已识别 \(result.speakerCount) 位说话人、\(result.speakerTurns.count) 个片段"
            }
            let decorated = result.utterances.compactMap { item -> String? in
                guard !item.text.isEmpty else { return nil }
                return "[说话人 \(item.speakerIndex + 1)] \(item.text)"
            }
            if !decorated.isEmpty { self.finals = decorated }
        }
    }

    nonisolated func onError(sessionId: String, errorCode: Int, errorMessage: String) {
        Task { @MainActor in
            guard self.sessionId == sessionId else { return }
            self.handleFailure("\(errorCode): \(errorMessage)")
        }
    }

    private func handleFailure(_ message: String) {
        recorder.stop()
        sessionId = nil
        isRecording = false
        isReplaying = false
        replayFrames.removeAll(keepingCapacity: true)
        errorMessage = message
        modelStatus = "failed"
    }

    private func resetCallbackCounts() {
        startCount = 0
        finalCount = 0
        lastCount = 0
        completeCount = 0
        lifecyclePassed = false
        publishCallbackSummary()
    }

    private func publishCallbackSummary() {
        callbackSummary = "start=\(startCount) final=\(finalCount) last=\(lastCount) complete=\(completeCount)"
    }
}

private enum WavFixture {
    enum FixtureError: Error { case invalidHeader, unsupportedFormat, missingData }

    static func frames(from url: URL) throws -> [Data] {
        let wav = try Data(contentsOf: url)
        guard wav.count >= 44,
              String(data: wav[0..<4], encoding: .ascii) == "RIFF",
              String(data: wav[8..<12], encoding: .ascii) == "WAVE" else {
            throw FixtureError.invalidHeader
        }

        var offset = 12
        var validFormat = false
        var pcm: Data?
        while offset + 8 <= wav.count {
            let chunkId = String(data: wav[offset..<(offset + 4)], encoding: .ascii)
            let size = Int(readUInt32(wav, offset + 4))
            let payload = offset + 8
            guard payload + size <= wav.count else { throw FixtureError.invalidHeader }
            if chunkId == "fmt ", size >= 16 {
                let format = readUInt16(wav, payload)
                let channels = readUInt16(wav, payload + 2)
                let sampleRate = readUInt32(wav, payload + 4)
                let bits = readUInt16(wav, payload + 14)
                validFormat = format == 1 && channels == 1 && sampleRate == 16_000 && bits == 16
            } else if chunkId == "data" {
                pcm = Data(wav[payload..<(payload + size)])
            }
            offset = payload + size + (size % 2)
        }
        guard validFormat else { throw FixtureError.unsupportedFormat }
        guard let pcm else { throw FixtureError.missingData }

        var frames: [Data] = []
        var start = 0
        while start + DINGQIAO_AUDIO_FRAME_BYTES <= pcm.count {
            frames.append(pcm.subdata(in: start..<(start + DINGQIAO_AUDIO_FRAME_BYTES)))
            start += DINGQIAO_AUDIO_FRAME_BYTES
        }
        guard !frames.isEmpty else { throw FixtureError.missingData }
        return frames
    }

    private static func readUInt16(_ data: Data, _ offset: Int) -> UInt16 {
        UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
    }

    private static func readUInt32(_ data: Data, _ offset: Int) -> UInt32 {
        UInt32(data[offset]) |
            (UInt32(data[offset + 1]) << 8) |
            (UInt32(data[offset + 2]) << 16) |
            (UInt32(data[offset + 3]) << 24)
    }
}

// MARK: - Mic recorder

/// 简易麦克风采集；16 kHz / mono / float32。生产环境建议用 AVAudioEngine + AVAudioConverter
/// 拿原生 sample rate 再下采样，这里是 demo 复杂度。
final class MicRecorder {
    private let engine = AVAudioEngine()
    private let targetSampleRate: Double = 16000
    private let frameLock = NSLock()
    private var converter: AVAudioConverter?
    private var pendingPcm = Data()
    private var tapInstalled = false

    func start(source: DemoAudioSource,
               onFrame: @escaping (Data) -> Void,
               onError: @escaping (Error) -> Void) {
        frameLock.lock()
        pendingPcm.removeAll(keepingCapacity: true)
        frameLock.unlock()
        let session = AVAudioSession.sharedInstance()
        do {
            let mode: AVAudioSession.Mode = source == .communication ? .voiceChat : .measurement
            try session.setCategory(.playAndRecord, mode: mode, options: [.defaultToSpeaker, .allowBluetoothHFP])
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
            var converted = Data(capacity: n * MemoryLayout<Int16>.size)
            for sample in UnsafeBufferPointer(start: chans[0], count: n) {
                let clipped = max(-1, min(1, sample))
                var pcm = Int16(clipped * Float(Int16.max)).littleEndian
                converted.append(Data(bytes: &pcm, count: MemoryLayout<Int16>.size))
            }
            var frames: [Data] = []
            self.frameLock.lock()
            self.pendingPcm.append(converted)
            while self.pendingPcm.count >= DINGQIAO_AUDIO_FRAME_BYTES {
                frames.append(Data(self.pendingPcm.prefix(DINGQIAO_AUDIO_FRAME_BYTES)))
                self.pendingPcm.removeFirst(DINGQIAO_AUDIO_FRAME_BYTES)
            }
            self.frameLock.unlock()
            frames.forEach(onFrame)
        }
        tapInstalled = true
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            tapInstalled = false
            onError(error)
        }
    }

    func stop() {
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        engine.stop()
        frameLock.lock()
        pendingPcm.removeAll(keepingCapacity: true)
        frameLock.unlock()
    }
}

// MARK: - Preview

struct ContentView_Previews: PreviewProvider {
    static var previews: some View { ContentView() }
}
