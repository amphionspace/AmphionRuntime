import { common } from '@kit.AbilityKit';
import { AsrConfig } from 'amphion_asr';
import { PoliceAssets } from './PoliceAssets';

export class PoliceEngineConfig {
  static readonly HOTWORDS_SCORE_DEFAULT: number = 3.0;
  static readonly HOTWORD_POOL_PLACEHOLDER: string = '__placeholder__';
  static readonly NUM_THREADS: number = 4;

  static effectiveHotwords(context: common.Context, extraHotwords: string[] = [], plate: boolean = true,
    station: boolean = true, terms: boolean = true): string[] {
    const seen = new Set<string>();
    const words: string[] = [];
    const append = (value: string): void => {
      const normalized = value.trim();
      if (normalized.length > 0 && !seen.has(normalized)) {
        seen.add(normalized);
        words.push(normalized);
      }
    };
    for (let i = 0; i < extraHotwords.length; i++) append(extraHotwords[i]);
    if (terms) PoliceAssets.readHotwords(context, 'terms').forEach(append);
    if (plate) PoliceAssets.readHotwords(context, 'plate').forEach(append);
    if (station) PoliceAssets.readHotwords(context, 'station').forEach(append);
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
