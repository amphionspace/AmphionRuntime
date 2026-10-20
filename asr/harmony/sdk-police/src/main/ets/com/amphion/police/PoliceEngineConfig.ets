import { common } from '@kit.AbilityKit';
import { AsrConfig } from 'amphion_asr';
import { PoliceAssets } from './PoliceAssets';

export class PoliceEngineConfig {
  /** 预置池（车牌/派出所/术语）的加权分。Police 1.4.0 的候选校准权重，避免短预置词过度覆盖声学结果。 */
  static readonly HOTWORDS_SCORE_DEFAULT: number = 1.0;
  /**
   * 调用方热词（sysGeneralLexicon）的逐词加权分。预置池按 1.4.0 校准停在
   * HOTWORDS_SCORE_DEFAULT=1.0，但该档对业务专名偏置不足——同音常用词仍会胜出
   * （「鼎桥」被识别成「顶桥」）。3.0 是 docs/asr/AISHELL3_HOTWORDS_EVAL.md 的工作点
   * （热词精确命中率 76.41% → 96.12%），也是车牌 A/B 实测确认的中档。
   */
  static readonly USER_HOTWORDS_SCORE: number = 3.0;
  static readonly HOTWORD_POOL_PLACEHOLDER: string = '__placeholder__';
  static readonly NUM_THREADS: number = 4;

  /**
   * sherpa-onnx hotwords buffer 的逐词加权语法：`<词> :<分>`。未标注的行回落到
   * ContextGraph 的全局 context_score（= AsrConfig.hotwordsScore），所以两档可以同池共存。
   */
  private static weighted(word: string, score: number): string {
    return `${word} :${score.toFixed(1)}`;
  }

  /** 去掉逐词加权后缀，用于把热词回显给用户。 */
  static displayText(entry: string): string {
    const marker = entry.lastIndexOf(' :');
    return marker < 0 ? entry : entry.substring(0, marker);
  }

  static effectiveHotwords(context: common.Context, extraHotwords: string[] = [], plate: boolean = true,
    station: boolean = true, terms: boolean = true): string[] {
    const seen = new Set<string>();
    const words: string[] = [];
    // score 省略表示沿用全局 hotwordsScore；调用方热词显式带 USER_HOTWORDS_SCORE。
    // 注意 seen 以原词去重，保证同一短语不会同时以带分和不带分两种形式进池。
    const append = (value: string, score?: number): void => {
      const normalized = value.trim();
      if (normalized.length === 0 || seen.has(normalized)) return;
      seen.add(normalized);
      words.push(score === undefined ? normalized : PoliceEngineConfig.weighted(normalized, score));
    };
    for (let i = 0; i < extraHotwords.length; i++) {
      append(extraHotwords[i], PoliceEngineConfig.USER_HOTWORDS_SCORE);
    }
    const appendPreset = (value: string): void => append(value);
    if (terms) PoliceAssets.readHotwords(context, 'terms').forEach(appendPreset);
    if (plate) PoliceAssets.readHotwords(context, 'plate').forEach(appendPreset);
    if (station) PoliceAssets.readHotwords(context, 'station').forEach(appendPreset);
    if (words.length > 0) return words;
    return extraHotwords.length > 0 || plate || station || terms ? [PoliceEngineConfig.HOTWORD_POOL_PLACEHOLDER] : [];
  }

  static build(context: common.Context, extraHotwords: string[] = [], plate: boolean = true,
    station: boolean = true, terms: boolean = true): AsrConfig {
    const config = new AsrConfig();
    config.numThreads = PoliceEngineConfig.NUM_THREADS;
    config.punctuation = true;
    config.itn = true;
    config.vad = true;
    config.endpoint = true;
    config.hotwordsScore = PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT;
    config.hotwords = PoliceEngineConfig.effectiveHotwords(context, extraHotwords, plate, station, terms);
    return config;
  }
}
