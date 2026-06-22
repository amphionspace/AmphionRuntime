import { AsrConfig } from 'amphion_asr';

export class PoliceEngineConfig {
  static readonly HOTWORDS_SCORE_DEFAULT: number = 5.0;

  static effectiveHotwords(extraHotwords: string[] = [], plate: boolean = true, station: boolean = true, terms: boolean = true): string[] {
    const words: string[] = [];
    if (plate) words.push('车牌号', '冀R', '辽B', '机动车', '号牌');
    if (station) words.push('派出所', '接警', '警情', '接警数据', '多少起');
    if (terms) words.push('处警', '派警', '核查', '嫌疑人', '身份证');
    for (const w of extraHotwords) {
      if (w.length > 0) words.push(w);
    }
    return Array.from(new Set(words));
  }

  static build(extraHotwords: string[] = [], plate: boolean = true, station: boolean = true, terms: boolean = true): AsrConfig {
    const config = new AsrConfig();
    config.punctuation = true;
    config.itn = true;
    config.vad = true;
    config.endpoint = true;
    config.hotwordsScore = PoliceEngineConfig.HOTWORDS_SCORE_DEFAULT;
    config.hotwords = PoliceEngineConfig.effectiveHotwords(extraHotwords, plate, station, terms);
    return config;
  }
}
