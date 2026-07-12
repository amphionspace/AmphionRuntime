import { AsrConfig, AsrLanguage } from './Types';

export class AssetBundle {
  bundleId: string;
  rawfileSubPath: string;
  files: string[];

  constructor(bundleId: string, rawfileSubPath: string, files: string[]) {
    this.bundleId = bundleId;
    this.rawfileSubPath = rawfileSubPath;
    this.files = files;
  }
}

export class InstalledLayout {
  asrDir: string = '';
  asrEncoder: string = '';
  asrDecoder: string = '';
  asrJoiner: string = '';
  asrTokens: string = '';
  asrBpeVocab: string = '';
  punctModel?: string;
  itnTagger?: string;
  itnVerbalizer?: string;
  vadModel?: string;
}

export class AssetRegistry {
  static readonly ROOT: string = 'amphion-models';

  static asrBundle(language: AsrLanguage): AssetBundle {
    if (language === AsrLanguage.YUE_EN) {
      return new AssetBundle('yue-en/v1', `${AssetRegistry.ROOT}/yue-en/v1`, [
        'encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt', 'bbpe.vocab'
      ]);
    }
    return new AssetBundle('zh-en/v1', `${AssetRegistry.ROOT}/zh-en/v1`, [
      'encoder.int8.ort', 'decoder.ort', 'joiner.int8.ort', 'tokens.txt', 'bbpe.vocab'
    ]);
  }

  static requiredBundles(language: AsrLanguage, config: AsrConfig): AssetBundle[] {
    const bundles: AssetBundle[] = [AssetRegistry.asrBundle(language)];
    if (config.punctuation) {
      bundles.push(new AssetBundle('punct-zhen/v1', `${AssetRegistry.ROOT}/punct-zhen/v1`, ['model.int8.ort']));
    }
    if (config.itn && language === AsrLanguage.ZH_EN) {
      bundles.push(new AssetBundle('itn-zh/v1', `${AssetRegistry.ROOT}/itn-zh/v1`, [
        'zh_itn_tagger.fst', 'zh_itn_verbalizer.fst'
      ]));
    }
    if (config.vad) {
      bundles.push(new AssetBundle('vad/v1', `${AssetRegistry.ROOT}/vad/v1`, ['silero_vad.onnx']));
    }
    return bundles;
  }

  static rawfileLayout(language: AsrLanguage, config: AsrConfig): InstalledLayout {
    const asr = AssetRegistry.asrBundle(language).rawfileSubPath;
    const layout = new InstalledLayout();
    layout.asrDir = asr;
    if (language === AsrLanguage.YUE_EN) {
      layout.asrEncoder = `${asr}/encoder.int8.onnx`;
      layout.asrDecoder = `${asr}/decoder.onnx`;
      layout.asrJoiner = `${asr}/joiner.int8.onnx`;
    } else {
      layout.asrEncoder = `${asr}/encoder.int8.ort`;
      layout.asrDecoder = `${asr}/decoder.ort`;
      layout.asrJoiner = `${asr}/joiner.int8.ort`;
    }
    layout.asrTokens = `${asr}/tokens.txt`;
    layout.asrBpeVocab = `${asr}/bbpe.vocab`;
    if (config.punctuation) layout.punctModel = `${AssetRegistry.ROOT}/punct-zhen/v1/model.int8.ort`;
    if (config.itn && language === AsrLanguage.ZH_EN) {
      layout.itnTagger = `${AssetRegistry.ROOT}/itn-zh/v1/zh_itn_tagger.fst`;
      layout.itnVerbalizer = `${AssetRegistry.ROOT}/itn-zh/v1/zh_itn_verbalizer.fst`;
    }
    if (config.vad) layout.vadModel = `${AssetRegistry.ROOT}/vad/v1/silero_vad.onnx`;
    return layout;
  }
}
