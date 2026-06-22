import { TtsVoiceInfo } from './TtsTypes';

/**
 * Kokoro 中英双语模型的 rawfile 布局。模型按 `rawfile/amphion-tts/<voiceId>/` 打包，
 * 与 Android TTS 交付保持一致。除 `dataDir`（espeak-ng-data）需要解包到沙箱外，
 * 其余文件由上游 sherpa_onnx 通过 ResourceManager 直接按 rawfile 相对路径读取。
 */
export class TtsModelLayout {
  voiceId: string = '';
  modelType: string = 'kokoro';
  rawfileDir: string = '';
  model: string = '';
  voices: string = '';
  tokens: string = '';
  lexicon: string = '';
  dataDirRawfile: string = '';
  ruleFsts: string = '';
}

export class TtsAssetRegistry {
  static readonly ROOT: string = 'amphion-tts';

  static layoutFor(voiceId: string): TtsModelLayout {
    const id = voiceId.length > 0 ? voiceId : 'kokoro-zh-en';
    const dir = `${TtsAssetRegistry.ROOT}/${id}`;
    const layout = new TtsModelLayout();
    layout.voiceId = id;
    layout.modelType = 'kokoro';
    layout.rawfileDir = dir;
    layout.model = `${dir}/model.onnx`;
    layout.voices = `${dir}/voices.bin`;
    layout.tokens = `${dir}/tokens.txt`;
    layout.lexicon = `${dir}/lexicon-us-en.txt,${dir}/lexicon-zh.txt`;
    layout.dataDirRawfile = `${dir}/espeak-ng-data`;
    layout.ruleFsts = `${dir}/date-zh.fst,${dir}/phone-zh.fst,${dir}/number-zh.fst`;
    return layout;
  }

  static voices(): TtsVoiceInfo[] {
    return [
      new TtsVoiceInfo('zh-en', 'kokoro-zh-en', 'female', 'Kokoro 中英双语女声')
    ];
  }
}
