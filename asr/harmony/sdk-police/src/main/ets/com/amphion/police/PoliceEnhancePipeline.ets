export class PoliceEnhanceResult {
  text: string = '';
  plateChanged: boolean = false;
  stationChanged: boolean = false;
  termsChanged: boolean = false;
}

export class PoliceEnhanceOptions {
  plateNormalizeEnabled: boolean = true;
  stationNormalizeEnabled: boolean = true;
  termsNormalizeEnabled: boolean = true;
}

export class PoliceEnhancePipeline {
  private options: PoliceEnhanceOptions;

  constructor(options?: PoliceEnhanceOptions) {
    this.options = options ?? new PoliceEnhanceOptions();
  }

  static create(options?: PoliceEnhanceOptions): PoliceEnhancePipeline {
    return new PoliceEnhancePipeline(options);
  }

  enhance(asrFinalText: string): PoliceEnhanceResult {
    let text = asrFinalText.trim();
    const result = new PoliceEnhanceResult();
    if (this.options.termsNormalizeEnabled) {
      const before = text;
      text = this.applyTerms(text);
      result.termsChanged = before !== text;
    }
    if (this.options.plateNormalizeEnabled) {
      const before = text;
      text = this.applyPlate(text);
      result.plateChanged = before !== text;
    }
    if (this.options.stationNormalizeEnabled) {
      const before = text;
      text = this.applyStation(text);
      result.stationChanged = before !== text;
    }
    result.text = text;
    return result;
  }

  close(): void {}

  private applyTerms(text: string): string {
    return text
      .replace(/接近/g, '接警')
      .replace(/处井/g, '处警')
      .replace(/派井/g, '派警');
  }

  private applyPlate(text: string): string {
    // Android 车牌增强的首版鸿蒙映射：保留冀R/辽B的常见口误归一，避免在通用语音中扩大误补范围。
    let s = text
      .replace(/记二/g, '冀R')
      .replace(/继尔/g, '冀R')
      .replace(/聊B/g, '辽B')
      .replace(/辽比/g, '辽B');
    s = s.replace(/车牌号([0-9]{5})(?![0-9])/g, (_match: string, tail: string) => `车牌号冀R${tail}`);
    return s;
  }

  private applyStation(text: string): string {
    let s = text;
    s = s.replace(/接警多少[？?]?$/g, '接警多少起。');
    s = s.replace(/接警多[。]?$/g, '接警多少起。');
    s = s.replace(/接警数[。]?$/g, '接警数据。');
    if (s.endsWith('？') || s.endsWith('?')) s = `${s.substring(0, s.length - 1)}。`;
    if (s.length > 0 && !s.endsWith('。')) s += '。';
    return s;
  }
}
