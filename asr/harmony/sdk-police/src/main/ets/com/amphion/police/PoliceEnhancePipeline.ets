import { common } from '@kit.AbilityKit';
import { PlateV2 } from './PlateV2';
import { PoliceStationV2 } from './PoliceStationV2';
import { PoliceTermsV2 } from './PoliceTermsV2';

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
  plateContextProvinces: string[] = ['冀', '辽'];
}

/** Android Dingqiao V2 parity pipeline: terms -> plate -> station. */
export class PoliceEnhancePipeline {
  private options: PoliceEnhanceOptions;
  private terms: PoliceTermsV2;
  private plate: PlateV2;
  private station: PoliceStationV2;

  constructor(context: common.Context, options?: PoliceEnhanceOptions) {
    this.options = options ?? new PoliceEnhanceOptions();
    this.terms = new PoliceTermsV2(context);
    this.plate = new PlateV2(context, this.options.plateContextProvinces);
    this.station = new PoliceStationV2(context);
  }

  static create(context: common.Context, options?: PoliceEnhanceOptions): PoliceEnhancePipeline {
    return new PoliceEnhancePipeline(context, options);
  }

  enhance(asrFinalText: string): PoliceEnhanceResult {
    const result = new PoliceEnhanceResult();
    let text = asrFinalText;
    if (this.options.termsNormalizeEnabled) {
      const normalized = this.terms.normalize(text);
      result.termsChanged = normalized !== text;
      text = normalized;
    }
    if (this.options.plateNormalizeEnabled) {
      const normalized = this.plate.normalize(text);
      result.plateChanged = normalized !== text;
      text = normalized;
    }
    if (this.options.stationNormalizeEnabled) {
      const normalized = this.station.normalize(text);
      result.stationChanged = normalized !== text;
      text = normalized;
    }
    result.text = text;
    return result;
  }

  close(): void {}
}
