import Foundation

internal enum DingqiaoLifecycleAction: Equatable {
    case requestNativeFinish
    case closeWithoutCallbacks
    case noOp
}

internal struct DingqiaoLifecycleGate {
    private enum Phase: Equatable {
        case idle
        case listening(String)
        case finishing(String)
        case terminalDelivered(String)
        case cancelled(String)
        case completed(String)
        case shutdown
    }

    private var phase: Phase = .idle
    private var shutdownPending = false

    var isBusy: Bool {
        switch phase {
        case .listening, .finishing, .terminalDelivered: return true
        default: return false
        }
    }

    var isShutdown: Bool { phase == .shutdown }

    func acceptsAudio(sessionId: String) -> Bool {
        phase == .listening(sessionId)
    }

    func ignoresLateAudio(sessionId: String) -> Bool {
        switch phase {
        case .finishing(sessionId), .terminalDelivered(sessionId): return true
        default: return false
        }
    }

    mutating func start(sessionId: String) throws {
        guard !isBusy else { throw DingqiaoParameterError.invalid("engine is busy") }
        guard phase != .shutdown else { throw DingqiaoParameterError.invalid("engine is destroyed") }
        phase = .listening(sessionId)
    }

    mutating func finish(sessionId: String) throws -> DingqiaoLifecycleAction {
        switch phase {
        case .listening(sessionId):
            phase = .finishing(sessionId)
            return .requestNativeFinish
        case .finishing(sessionId), .terminalDelivered(sessionId), .cancelled(sessionId), .completed(sessionId):
            return .noOp
        default:
            throw DingqiaoParameterError.invalid("finish failed for inactive session")
        }
    }

    mutating func cancel(sessionId: String) throws -> DingqiaoLifecycleAction {
        switch phase {
        case .listening(sessionId), .finishing(sessionId):
            phase = .cancelled(sessionId)
            return .closeWithoutCallbacks
        case .cancelled(sessionId), .completed(sessionId):
            return .noOp
        default:
            throw DingqiaoParameterError.invalid("cancel failed for inactive session")
        }
    }

    mutating func acceptResult(sessionId: String, isLast: Bool) throws -> Bool {
        switch phase {
        case .listening(sessionId):
            guard !isLast else {
                throw DingqiaoParameterError.invalid("isLast received before a terminal condition")
            }
            return true
        case .finishing(sessionId):
            if isLast { phase = .terminalDelivered(sessionId) }
            return true
        case .cancelled(sessionId), .terminalDelivered(sessionId):
            return false
        default:
            return false
        }
    }

    mutating func complete(sessionId: String) -> Bool {
        guard phase == .terminalDelivered(sessionId) else { return false }
        phase = shutdownPending ? .shutdown : .completed(sessionId)
        shutdownPending = false
        return true
    }

    mutating func shutdown() -> DingqiaoLifecycleAction {
        switch phase {
        case .finishing, .terminalDelivered:
            shutdownPending = true
            return .noOp
        case .listening:
            phase = .shutdown
            return .closeWithoutCallbacks
        case .shutdown:
            return .noOp
        default:
            phase = .shutdown
            return .noOp
        }
    }
}
