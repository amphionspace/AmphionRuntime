import Foundation

func expect(_ condition: Bool, _ message: String) {
    guard condition else {
        fatalError("contract smoke failed: \(message)")
    }
}

let create = DingqiaoCreateEngineParams(extraParams: ["recognizerMode": "long"])
let start = DingqiaoStartParams(
    sessionId: "smoke_1",
    extraParams: ["recognizerMode": "short", "maxAudioDuration": "60000"]
)
let options = try DingqiaoParameterPolicy.parse(create: create, start: start)
expect(options.recognizerMode == "short", "session recognizerMode must override engine mode")
expect(options.maxAudioDurationMs == 60_000, "numeric strings must match Android/Harmony")

var gate = DingqiaoLifecycleGate()
try gate.start(sessionId: "smoke_1")
expect(try gate.acceptResult(sessionId: "smoke_1", isLast: false), "partial/final must pass while listening")
expect(try gate.finish(sessionId: "smoke_1") == .requestNativeFinish, "first finish must flush native")
expect(try gate.finish(sessionId: "smoke_1") == .noOp, "repeated finish must be idempotent")
expect(gate.ignoresLateAudio(sessionId: "smoke_1"), "late PCM after finish must be ignored")
expect(try gate.acceptResult(sessionId: "smoke_1", isLast: true), "one native last must pass")
expect(!(try gate.acceptResult(sessionId: "smoke_1", isLast: true)), "duplicate last must be suppressed")
expect(gate.complete(sessionId: "smoke_1"), "last must be followed by one complete")
expect(!gate.complete(sessionId: "smoke_1"), "duplicate complete must be suppressed")
expect(!gate.isBusy, "engine must recover after complete")

var cancelGate = DingqiaoLifecycleGate()
try cancelGate.start(sessionId: "cancel")
expect(try cancelGate.cancel(sessionId: "cancel") == .closeWithoutCallbacks, "cancel must close native")
expect(!(try cancelGate.acceptResult(sessionId: "cancel", isLast: true)), "cancel must suppress final")
expect(!cancelGate.complete(sessionId: "cancel"), "cancel must suppress complete")

var shutdownGate = DingqiaoLifecycleGate()
try shutdownGate.start(sessionId: "shutdown")
_ = try shutdownGate.finish(sessionId: "shutdown")
expect(shutdownGate.shutdown() == .noOp, "finishing shutdown must wait for native tail")
expect(try shutdownGate.acceptResult(sessionId: "shutdown", isLast: true), "shutdown tail must pass")
expect(shutdownGate.complete(sessionId: "shutdown"), "shutdown must close after complete")
expect(shutdownGate.isShutdown, "engine must be destroyed after deferred shutdown")

print("iOS Dingqiao contract smoke PASS")
