Pod::Spec.new do |s|
  s.name             = 'AmphionRuntime'
  s.version          = '0.3.4-alpha.1'
  s.summary          = 'AmphionRuntime iOS ASR 与鼎桥兼容层预览版'
  s.description      = <<-DESC
    基础 ASR API 与 Android AmphionRuntime 使用相同模型和 PCM 契约；鼎桥参数与生命周期
    正在按 shared/api-spec 分阶段对齐，未完成能力会显式失败：
    AsrSdk / AsrConfig / AsrEngine / AsrSession / AsrCallback / AsrError / AsrResult / ModelManager / ModelDescriptor / ModelType。

    跨端不变量：manifest.json schema、错误码段、tokens.txt 协议、PCM 16kHz mono。
  DESC

  s.homepage         = 'https://github.com/amphionspace/AmphionRuntime'
  s.license          = { :type => 'Apache-2.0' }
  s.author           = { 'Amphion Voice Team' => 'voice@amphion.example' }

  s.source           = {
    :git => 'https://github.com/amphionspace/AmphionRuntime.git',
    :tag => "v#{s.version}"
  }

  s.ios.deployment_target = '13.0'
  s.swift_versions = ['5.7']

  # SDK 源代码
  s.source_files = 'Sources/AmphionRuntime/**/*.swift', 'Sources/SherpaOnnxBridge/**/*.swift'
  s.frameworks   = 'AVFoundation', 'CoreAudio'

  # 当前开发版通过本地 :path 集成，并使用 build_xcframework.sh 生成的 framework。
  s.vendored_frameworks = 'AmphionRuntime.xcframework'

  s.requires_arc = true
  s.pod_target_xcconfig = {
    'EXCLUDED_ARCHS[sdk=iphonesimulator*]' => 'i386',
  }
end
