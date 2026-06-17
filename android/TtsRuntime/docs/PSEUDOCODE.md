# Lits TTS Android SDK 伪代码

本文给交付 SDK 的接入方提供一份从查询音色到释放引擎的完整流程示例。字段和值以当前 Android AAR 实际支持能力为准。

## 1. 完整流程

```pseudocode
// 0. 可选：查询可用音色
voices = TextToSpeechSdk.listVoices(VoiceQuery {
    requestId: "voices-001",
    mode: OFFLINE,
    language: "zh-en"
})

// 1. 可选：指定 SDK 工作目录
TextToSpeechSdk.setWorkPath("<filesDir>/lits-tts")

// 2. 创建引擎并在 createEngine 阶段加载模型
params = CreateEngineParams {
    language: "zh-en",
    mode: OFFLINE,
    voiceId: "lits-female-01",
    locate: "CN",
    engineName: "xiaoqiao-tts",
    modelLoadOnCreate: true
}
engine = TextToSpeechSdk.createEngine(params)

// 3. 注册监听器
engine.setListener(SpeakListener {
    onStart(requestId, response):
        log("start requestId=" + requestId
            + " sampleRate=" + response.sampleRate)

    onData(requestId, audio, response):
        // 仅在 playType=SYNTHESIZE_ONLY 时接收 PCM 分片
        buffer.put(response.sequence, audio)

    onComplete(requestId, response):
        if response.type == SYNTHESIS_COMPLETE:
            log("synthesis done requestId=" + requestId)
        if response.type == PLAYBACK_COMPLETE:
            log("playback done requestId=" + requestId)

    onStop(requestId, response):
        log("stopped requestId=" + requestId)

    onError(requestId, code, msg):
        log("error requestId=" + requestId + " code=" + code + " msg=" + msg)
})

// 4. 合成并由 SDK 内部播放
engine.speak("您好，有什么可以帮您？", SpeakParams {
    requestId: "play-001",
    speed: 1.0,
    volume: 1.0,
    pitch: 1.0,
    languageContext: "zh-en",
    audioType: "pcm",
    playType: SYNTHESIZE_AND_PLAY,
    queueMode: PREEMPT
})

// 5. 仅合成并通过 onData 接收 PCM
engine.speak("hello world", SpeakParams {
    requestId: "pcm-001",
    playType: SYNTHESIZE_ONLY,
    queueMode: QUEUE
})

// 6. 可选：停止全部任务
engine.stop()

// 7. 释放资源
engine.shutdown()
```

## 2. Android 推荐接入方式

Android App 推荐优先使用 callback 版 `createEngine` 做预加载，不要在主线程调用同步版创建接口。

```pseudocode
TextToSpeechSdk.setWorkPath("<filesDir>/lits-tts")

TextToSpeechSdk.createEngine(params, Callback {
    onSuccess(engine):
        engine.setListener(listener)
        cache(engine)

    onError(code, message):
        reportInitFailure(code, message)
})
```

## 3. 关键约束

- `mode` 当前仅支持 `OFFLINE`。
- `modelLoadOnCreate` 当前仅支持 `true`。
- `requestId` 在同一引擎实例内必须唯一，`VoiceQuery.requestId` 也必须非空。
- `setListener` 必须早于 `speak`。
- `locate` 默认值为 `CN`；如需其他地区可传自定义字符串，但不能传空串。
- `voiceId` 代表 speaker 身份；同一个 `voiceId` 可在多个 `language` 下复用。
- `engineName` 用于多实例区分；如传入则不能是空串。
- `languageContext` 当前支持 `zh-en` 和 `en-US`；用于控制数字等局部读法上下文。
- `audioType` 当前仅支持 `pcm`。

## 4. 当前内置音色

| language | voiceId | gender |
| --- | --- | --- |
| `zh-en` | `lits-female-01` | `Female` |
| `zh-en` | `lits-female-02` | `Female` |
| `en-US` | `lits-female-01` | `Female` |
| `en-US` | `lits-female-02` | `Female` |
