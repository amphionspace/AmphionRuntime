Pod::Spec.new do |s|
  s.name             = 'AmphionRuntime'
  s.version          = '0.1.0'
  s.summary          = 'AmphionRuntime iOS 端，基于 sherpa-onnx 流式 zipformer'
  s.description      = <<-DESC
    Public API 与 Android AmphionRuntime 一一对齐：
    AsrSdk / AsrConfig / AsrEngine / AsrSession / AsrCallback / AsrError / AsrResult / ModelManager / ModelDescriptor / ModelType。

    跨端不变量：manifest.json schema、错误码段、tokens.txt 协议、PCM 16kHz mono。
  DESC

  s.homepage         = 'https://your-internal-git/amphion/amphion-runtime-ios'
  s.license          = { :type => 'Apache-2.0', :file => 'LICENSE' }
  s.author           = { 'Amphion Voice Team' => 'voice@amphion.example' }

  s.source           = {
    :git => 'https://your-internal-git/amphion/amphion-runtime-ios.git',
    :tag => "v#{s.version}"
  }

  s.ios.deployment_target = '13.0'
  s.swift_versions = ['5.7']

  # SDK 源代码
  s.source_files = 'Sources/AmphionRuntime/**/*.swift', 'Sources/SherpaOnnxBridge/**/*.swift'
  s.frameworks   = 'AVFoundation', 'CoreAudio'

  # 二进制 framework：CI 产出后挂在公司私有 OSS / GitHub Releases，
  # 替换 :http 与 :sha256 为真实地址：
  s.vendored_frameworks = 'AmphionRuntime.xcframework'
  # 或者：
  # s.subspec 'Binary' do |bin|
  #   bin.source = {
  #     :http => 'https://your-cdn.example.com/amphion-runtime/0.1.0/AmphionRuntime.xcframework.zip',
  #     :sha256 => 'REPLACE_ME'
  #   }
  # end

  s.requires_arc = true
  s.pod_target_xcconfig = {
    'EXCLUDED_ARCHS[sdk=iphonesimulator*]' => 'i386',
  }
end
