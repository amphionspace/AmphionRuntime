import { common } from '@kit.AbilityKit';
import hilog from '@ohos.hilog';
import { PlateV2 } from './PlateV2';
import { PoliceStationV2 } from './PoliceStationV2';
import { PoliceTermsV2 } from './PoliceTermsV2';
import { PersonNameNormalizer } from './PersonNameNormalizer';
import { PoliceTextProvenance, PoliceTextTrace } from './PoliceTextTrace';

export class PoliceEnhanceResult {
  text: string = '';
  plateChanged: boolean = false;
  stationChanged: boolean = false;
  termsChanged: boolean = false;
  personNameChanged: boolean = false;
  // Input-to-output records when the text changed and every step was traced.
  provenance?: PoliceTextProvenance;
}

export class PoliceEnhanceOptions {
  plateNormalizeEnabled: boolean = true;
  stationNormalizeEnabled: boolean = true;
  termsNormalizeEnabled: boolean = true;
  plateContextProvinces: string[] = ['冀', '辽'];
}

/** Android Dingqiao V2 parity pipeline plus fail-soft person-name correction. */
export class PoliceEnhancePipeline {
  private options: PoliceEnhanceOptions;
  private terms: PoliceTermsV2;
  private plate: PlateV2;
  private station: PoliceStationV2;
  private context: common.Context;
  private personNames?: PersonNameNormalizer;

  constructor(context: common.Context, options?: PoliceEnhanceOptions) {
    this.context = context;
    this.options = options ?? new PoliceEnhanceOptions();
    this.terms = new PoliceTermsV2(context);
    this.plate = new PlateV2(context, this.options.plateContextProvinces);
    this.station = new PoliceStationV2(context);
  }

  static create(context: common.Context, options?: PoliceEnhanceOptions): PoliceEnhancePipeline {
    return new PoliceEnhancePipeline(context, options);
  }

  configurePersonNames(customHotwords: string[]): void {
    this.personNames?.close();
    this.personNames = undefined;
    if (customHotwords.length > 0) {
      try {
        this.personNames = new PersonNameNormalizer(this.context, customHotwords);
        hilog.info(0x0000, 'AmphionPersonName',
          'person-name normalizer ready, customHotwordCount=%{public}d', customHotwords.length);
      } catch (e) {
        // LAC is an optional final-text enhancement. Never let an asset/model error break ASR.
        hilog.warn(0x0000, 'AmphionPersonName',
          'person-name normalizer disabled: %{public}s', `${e}`);
      }
    }
  }

  enhance(asrFinalText: string): PoliceEnhanceResult {
    const result = new PoliceEnhanceResult();
    const trace = new PoliceTextTrace(asrFinalText);
    let text = asrFinalText;
    if (this.options.termsNormalizeEnabled) {
      const normalized = this.terms.normalize(text, trace);
      result.termsChanged = normalized !== text;
      text = normalized;
    }
    if (this.options.plateNormalizeEnabled) {
      const normalized = this.plate.normalize(text, trace);
      result.plateChanged = normalized !== text;
      text = normalized;
    }
    if (this.options.stationNormalizeEnabled) {
      const normalized = this.station.normalize(text, trace);
      result.stationChanged = normalized !== text;
      text = normalized;
    }
    if (this.options.termsNormalizeEnabled) {
      const polished = this.terms.polish(text, trace);
      result.termsChanged = result.termsChanged || polished !== text;
      text = polished;
    }
    if (this.personNames !== undefined) {
      try {
        const normalized = this.personNames.normalize(text, trace);
        result.personNameChanged = normalized !== text;
        if (result.personNameChanged) {
          hilog.info(0x0000, 'AmphionPersonName',
            'PERSON_CORRECT before=%{public}s after=%{public}s', text, normalized);
        }
        text = normalized;
      } catch (e) {
        hilog.warn(0x0000, 'AmphionPersonName',
          'person-name normalize skipped: %{public}s', `${e}`);
      }
    }
    result.text = text;
    // A skipped (failed) step leaves the trace behind the text: no provenance.
    if (trace.matches(text)) result.provenance = trace.provenance();
    return result;
  }

  close(): void {
    this.personNames?.close();
    this.personNames = undefined;
  }
}
