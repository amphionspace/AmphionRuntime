import SwiftUI
import AmphionRuntime

@main
struct AmphionRuntimeSampleApp: App {
    init() {
        AsrSdk.shared.start()
    }
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
