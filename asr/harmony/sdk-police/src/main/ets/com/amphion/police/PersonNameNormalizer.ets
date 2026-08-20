import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { LacPersonNer, PersonEntitySpan } from 'amphion_asr';
import { PersonNameMatcher, PersonSpan } from './PersonNameMatcher';
import { PoliceAssets } from './PoliceAssets';

const LAC_RAW_ROOT: string = 'amphion-police/lac/v1';
const LAC_FILES: string[] = [
  'lac_encoder.onnx',
  'lac_crf_transitions.npy',
  'word.dic',
  'tag.dic',
  'q2b.dic'
];

/** LAC PER detection plus tone-aware exact-pinyin matching against custom hotwords. */
export class PersonNameNormalizer {
  private ner: LacPersonNer;
  private matcher: PersonNameMatcher;

  constructor(context: common.Context, customHotwords: string[]) {
    const root = PersonNameNormalizer.installAssets(context);
    this.ner = new LacPersonNer(
      `${root}/lac_encoder.onnx`,
      `${root}/lac_crf_transitions.npy`,
      `${root}/word.dic`,
      `${root}/tag.dic`,
      `${root}/q2b.dic`
    );
    const personNames: string[] = [];
    for (let i = 0; i < customHotwords.length; i++) {
      const name = customHotwords[i].trim();
      if (name.length < 2 || name.length > 6) continue;
      const spans = this.ner.findPersonSpans(name);
      for (let j = 0; j < spans.length; j++) {
        if (spans[j].start === 0 && spans[j].end === name.length) {
          personNames.push(name);
          break;
        }
      }
    }
    this.matcher = new PersonNameMatcher(
      PersonNameNormalizer.loadPinyin(PoliceAssets.readText(context, 'lac/v1/pinyin.tsv')),
      personNames
    );
  }

  normalize(text: string): string {
    if (text.length === 0) return text;
    const nativeSpans: PersonEntitySpan[] = this.ner.findPersonSpans(text);
    const spans: PersonSpan[] = [];
    for (let i = 0; i < nativeSpans.length; i++) {
      spans.push({ start: nativeSpans[i].start, end: nativeSpans[i].end });
    }
    return this.matcher.normalize(text, spans);
  }

  close(): void { this.ner.close(); }

  private static installAssets(context: common.Context): string {
    const root = `${context.filesDir}/amphion-police/lac/v1`;
    if (!fs.accessSync(root)) fs.mkdirSync(root, true);
    for (let i = 0; i < LAC_FILES.length; i++) {
      const file = LAC_FILES[i];
      const target = `${root}/${file}`;
      if (fs.accessSync(target)) continue;
      const bytes = context.resourceManager.getRawFileContentSync(`${LAC_RAW_ROOT}/${file}`);
      const fp = fs.openSync(target,
        fs.OpenMode.WRITE_ONLY | fs.OpenMode.CREATE | fs.OpenMode.TRUNC);
      try {
        fs.writeSync(fp.fd, bytes.buffer);
      } finally {
        fs.closeSync(fp.fd);
      }
    }
    return root;
  }

  private static loadPinyin(text: string): Map<string, string> {
    const result = new Map<string, string>();
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const tab = lines[i].indexOf('\t');
      if (tab <= 0) continue;
      const character = lines[i].substring(0, tab);
      const syllable = lines[i].substring(tab + 1).trim().toLowerCase();
      if (character.length === 1 && syllable.length > 0 && !result.has(character)) {
        result.set(character, syllable);
      }
    }
    return result;
  }
}
