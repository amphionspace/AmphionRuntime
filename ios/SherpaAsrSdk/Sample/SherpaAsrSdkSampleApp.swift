import SwiftUI
import SherpaAsrSdk

@main
struct SherpaAsrSdkSampleApp: App {
    init() {
        AsrSdk.shared.start()
    }
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
