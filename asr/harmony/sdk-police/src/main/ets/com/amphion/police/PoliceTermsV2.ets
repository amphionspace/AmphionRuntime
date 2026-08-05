import { common } from '@kit.AbilityKit';
import { PoliceAssetPair, PoliceAssets } from './PoliceAssets';

class TermMatch {
  term: string;
  consumed: number;

  constructor(term: string, consumed: number) {
    this.term = term;
    this.consumed = consumed;
  }
}

class TermReadingMap {
  private subs: Map<string, Set<string>> = new Map<string, Set<string>>();

  constructor(pairs: PoliceAssetPair[]) {
    for (let p = 0; p < pairs.length; p++) {
      const pair = pairs[p];
      if (pair.from.length === 0 || pair.from.length !== pair.to.length) continue;
      for (let i = 0; i < pair.from.length; i++) {
        const from = pair.from.charAt(i);
        const to = pair.to.charAt(i);
        if (from === to) continue;
        let targets = this.subs.get(from);
        if (targets === undefined) {
          targets = new Set<string>();
          this.subs.set(from, targets);
        }
        targets.add(to);
      }
    }
  }

  allows(from: string, to: string): boolean {
    if (from === to) return true;
    const targets = this.subs.get(from);
    return targets !== undefined && targets.has(to);
  }
}

class TermsHomophones {
  private pairs: PoliceAssetPair[];

  constructor(pairs: PoliceAssetPair[]) {
    this.pairs = pairs;
  }

  apply(text: string): string {
    let output = text;
    for (let i = 0; i < this.pairs.length; i++) {
      const pair = this.pairs[i];
      if (pair.from === pair.to) continue;
      output = pair.to.startsWith(pair.from) ?
        this.replaceExtending(output, pair.from, pair.to) : output.split(pair.from).join(pair.to);
    }
    return output;
  }

  private replaceExtending(text: string, from: string, to: string): string {
    let output = '';
    let cursor = 0;
    while (cursor <= text.length) {
      const index = text.indexOf(from, cursor);
      if (index < 0) return output + text.substring(cursor);
      output += text.substring(cursor, index);
      if (index + to.length <= text.length && text.substring(index, index + to.length) === to) {
        output += to;
        cursor = index + to.length;
      } else {
        output += to;
        cursor = index + from.length;
      }
    }
    return output;
  }
}

class RadioDigits {
  private static readonly STRONG: Map<string, string> = new Map<string, string>([
    ['洞', '0'], ['幺', '1'], ['拐', '7'], ['勾', '9'], ['钩', '9']
  ]);
  private static readonly WEAK: Map<string, string> = new Map<string, string>([
    ['两', '2'], ['三', '3'], ['四', '4'], ['五', '5'], ['六', '6'], ['八', '8'],
    ['沟', '9'], ['腰', '1'], ['撩', '1']
  ]);
  private static readonly MISHEAR: Map<string, string> = new Map<string, string>([
    ['栋', '0'], ['动', '0'], ['梁', '2']
  ]);

  private static isArabic(value: string): boolean {
    return value >= '0' && value <= '9';
  }

  private static isConvertible(value: string): boolean {
    return RadioDigits.isArabic(value) || RadioDigits.STRONG.has(value) ||
      RadioDigits.WEAK.has(value) || RadioDigits.MISHEAR.has(value);
  }

  static normalize(text: string): string {
    let output = '';
    let i = 0;
    while (i < text.length) {
      if (!RadioDigits.isConvertible(text.charAt(i))) {
        output += text.charAt(i++);
        continue;
      }
      let end = i;
      while (end < text.length && RadioDigits.isConvertible(text.charAt(end))) end++;
      output += RadioDigits.convertSegment(text.substring(i, end));
      i = end;
    }
    return output;
  }

  private static convertSegment(segment: string): string {
    let arabic = 0;
    let strong = 0;
    for (let i = 0; i < segment.length; i++) {
      const value = segment.charAt(i);
      if (RadioDigits.isArabic(value)) arabic++;
      else if (RadioDigits.STRONG.has(value)) strong++;
    }
    if (arabic + strong < 2 && (strong < 1 || segment.length < 3)) return segment;
    const allowMishear = arabic >= 3;
    let output = '';
    for (let i = 0; i < segment.length; i++) {
      const value = segment.charAt(i);
      if (RadioDigits.isArabic(value)) output += value;
      else if (RadioDigits.STRONG.has(value)) output += RadioDigits.STRONG.get(value);
      else if (RadioDigits.WEAK.has(value)) output += RadioDigits.WEAK.get(value);
      else if (allowMishear && RadioDigits.MISHEAR.has(value)) output += RadioDigits.MISHEAR.get(value);
      else output += value;
    }
    return output;
  }
}

class DengluGuard {
  private static readonly VARIANT: string = '登陆';
  // 登录语境词（近窗 6 字内出现才纠 登陆→登录）。
  private static readonly CTX: string[] = [
    '系统', '平台', '客户端', '门户', '账号', '帐号', '后台',
    '应用', '界面', '首页', '模块', '网站', '网页'
  ];
  // 登陆 后紧跟这些字为通用义（登陆作战/舰/艇/沿海/岛…），一律不纠。
  private static readonly COLLIDE: Set<string> = new Set<string>([
    '作', '演', '舰', '艇', '部', '战', '岛', '滩', '沿', '海', '月'
  ]);

  static apply(text: string): string {
    if (text.indexOf(DengluGuard.VARIANT) < 0) return text;
    let output = '';
    let i = 0;
    while (i <= text.length) {
      const idx = text.indexOf(DengluGuard.VARIANT, i);
      if (idx < 0) {
        output += text.substring(i);
        break;
      }
      output += text.substring(i, idx);
      const end = idx + DengluGuard.VARIANT.length;
      const after = end < text.length ? text.charAt(end) : '';
      const collide = after.length > 0 && DengluGuard.COLLIDE.has(after);
      const ctxAfter = text.substring(end, Math.min(end + 6, text.length));
      let hasCtx = false;
      for (let c = 0; c < DengluGuard.CTX.length; c++) {
        if (ctxAfter.indexOf(DengluGuard.CTX[c]) >= 0) {
          hasCtx = true;
          break;
        }
      }
      output += (!collide && hasCtx) ? '登录' : DengluGuard.VARIANT;
      i = end;
    }
    return output;
  }
}

class QzxVariant {
  variant: string;
  collide: Set<string>;

  constructor(variant: string, collide: string[]) {
    this.variant = variant;
    this.collide = new Set<string>(collide);
  }
}

// 二至三字警务短词缺少足够上下文，不能进入全局模糊层。这里只纠正整句命中，
// 或紧邻明确警务业务锚点的已知误识串；规则与 Android PoliceTermsShortGuard 对齐。
class PoliceShortTermGuard {
  private static readonly SENTENCE_END: Set<string> = new Set<string>([
    '。', '！', '？', '!', '?', '，', ',', '、', '；', ';', '：', ':'
  ]);

  private static readonly JUCHUAN_VARIANTS: string[] = ['喻传', '居传', '拒传'];
  private static readonly JUCHUAN_BEFORE: string[] = [
    '办理', '依法', '进行', '执行', '实施', '采取', '决定', '批准', '审批', '申请', '可以'
  ];
  private static readonly JUCHUAN_AFTER: string[] = [
    '到案', '审批', '手续', '措施', '决定', '对象', '期间', '期限', '程序', '执行'
  ];

  private static readonly JIECHUJING_VARIANTS: string[] = [
    '接触景', '接触警', '接触井', '接触颈', '接出警', '街处警'
  ];
  private static readonly JIECHUJING_BEFORE: string[] = ['移动', '指信'];
  private static readonly JIECHUJING_AFTER: string[] = [
    '流程', '记录', '规范', '工作', '机制', '系统', '平台', '业务', '要求', '要及时', '已上传'
  ];

  // 图片中「指信接处警」整词被听成「女性接触颈」；只在整句命中时纠正。
  private static readonly ZHIXIN_JIECHUJING_VARIANTS: string[] = [
    '女性接触颈', '女性接触景', '女性接触警', '女性接触井'
  ];

  static apply(text: string): string {
    if (text.length === 0) return text;

    let whole = PoliceShortTermGuard.replaceWholeUtterance(
      text, PoliceShortTermGuard.ZHIXIN_JIECHUJING_VARIANTS, '指信接处警');
    if (whole !== undefined) return whole;
    whole = PoliceShortTermGuard.replaceWholeUtterance(
      text, PoliceShortTermGuard.JUCHUAN_VARIANTS, '拘传');
    if (whole !== undefined) return whole;
    whole = PoliceShortTermGuard.replaceWholeUtterance(
      text, PoliceShortTermGuard.JIECHUJING_VARIANTS, '接处警');
    if (whole !== undefined) return whole;

    let output = PoliceShortTermGuard.replaceWithAnchors(
      text,
      PoliceShortTermGuard.JUCHUAN_VARIANTS,
      '拘传',
      PoliceShortTermGuard.JUCHUAN_BEFORE,
      PoliceShortTermGuard.JUCHUAN_AFTER);
    output = PoliceShortTermGuard.replaceWithAnchors(
      output,
      PoliceShortTermGuard.JIECHUJING_VARIANTS,
      '接处警',
      PoliceShortTermGuard.JIECHUJING_BEFORE,
      PoliceShortTermGuard.JIECHUJING_AFTER);
    return output;
  }

  private static replaceWholeUtterance(
    text: string,
    variants: string[],
    target: string
  ): string | undefined {
    let start = 0;
    while (start < text.length && PoliceShortTermGuard.isWhitespace(text.charAt(start))) start++;
    if (start >= text.length) return undefined;

    let end = text.length;
    while (end > start) {
      const value = text.charAt(end - 1);
      if (!PoliceShortTermGuard.isWhitespace(value) &&
        !PoliceShortTermGuard.SENTENCE_END.has(value)) break;
      end--;
    }
    if (end <= start) return undefined;

    const core = text.substring(start, end);
    if (variants.indexOf(core) < 0) return undefined;
    return text.substring(0, start) + target + text.substring(end);
  }

  private static replaceWithAnchors(
    text: string,
    variants: string[],
    target: string,
    beforeAnchors: string[],
    afterAnchors: string[]
  ): string {
    let output = text;
    for (let v = 0; v < variants.length; v++) {
      const variant = variants[v];
      let from = 0;
      while (from < output.length) {
        const index = output.indexOf(variant, from);
        if (index < 0) break;
        const end = index + variant.length;
        const before = output.substring(0, index);
        const after = output.substring(end);
        const accepted = PoliceShortTermGuard.endsWithAny(before, beforeAnchors) ||
          PoliceShortTermGuard.startsWithAny(after, afterAnchors);
        if (accepted) {
          output = output.substring(0, index) + target + output.substring(end);
          from = index + target.length;
        } else {
          from = end;
        }
      }
    }
    return output;
  }

  private static endsWithAny(text: string, anchors: string[]): boolean {
    for (let i = 0; i < anchors.length; i++) {
      if (text.endsWith(anchors[i])) return true;
    }
    return false;
  }

  private static startsWithAny(text: string, anchors: string[]): boolean {
    for (let i = 0; i < anchors.length; i++) {
      if (text.startsWith(anchors[i])) return true;
    }
    return false;
  }

  private static isWhitespace(value: string): boolean {
    return value.trim().length === 0;
  }
}

// 「情指行」上下文护栏：App 语境（前有打开X/后近窗出现平台等）下把误识变体纠回，
// 且未撞黑名单后继字（通用义）。与 Android PoliceTermsNormalizerV2.applyQingZhiXingGuard 对齐。
class QingZhiXingGuard {
  private static readonly TARGET: string = '情指行';
  private static readonly OPEN_VERBS: string[] = ['打开', '登录', '进入', '启动', '点击', '使用'];
  private static readonly APP_CTX: string[] = [
    '客户端', '平台', '系统', '首页', '模块', '上报', '签收', '下发', '指令', '勤务', '版本', '核心'
  ];
  // 误识变体 + 碰撞后继字黑名单（后紧跟这些字为通用义，不纠）。
  // 请执行=通用高频词，仅 App 语境纠；黑名单为真·动宾字(命令/任务/操作/结果/判决…)，
  // 不含 的/了/过 虚词——打开X 已是强 App 信号。
  private static readonly VARIANTS: QzxVariant[] = [
    new QzxVariant('请指信', ['息']),
    new QzxVariant('请执行', ['命', '任', '操', '程', '死', '判', '完', '以', '方', '决', '计', '结']),
    new QzxVariant('停止行', ['动', '为', '走', '驶', '车', '列', '进']),
    new QzxVariant('停止航', ['班', '行', '道', '向', '线'])
  ];

  static apply(text: string): string {
    if (text.length < 3) return text;
    let out = text;
    for (let v = 0; v < QingZhiXingGuard.VARIANTS.length; v++) {
      const item = QingZhiXingGuard.VARIANTS[v];
      const variant = item.variant;
      if (out.indexOf(variant) < 0) continue;
      let sb = '';
      let i = 0;
      while (i <= out.length) {
        const idx = out.indexOf(variant, i);
        if (idx < 0) {
          sb += out.substring(i);
          break;
        }
        sb += out.substring(i, idx);
        const end = idx + variant.length;
        const after = end < out.length ? out.charAt(end) : '';
        const collide = after.length > 0 && item.collide.has(after);
        const ctxAfter = out.substring(end, Math.min(end + 5, out.length));
        let hasAfterCtx = false;
        for (let c = 0; c < QingZhiXingGuard.APP_CTX.length; c++) {
          if (ctxAfter.indexOf(QingZhiXingGuard.APP_CTX[c]) >= 0) {
            hasAfterCtx = true;
            break;
          }
        }
        const before = out.substring(0, idx);
        let hasOpenVerb = false;
        for (let o = 0; o < QingZhiXingGuard.OPEN_VERBS.length; o++) {
          const verb = QingZhiXingGuard.OPEN_VERBS[o];
          if (before.endsWith(verb) || before.endsWith(verb + '，') ||
            before.endsWith(verb + ',') || before.endsWith(verb + '、')) {
            hasOpenVerb = true;
            break;
          }
        }
        sb += (!collide && (hasAfterCtx || hasOpenVerb)) ? QingZhiXingGuard.TARGET : variant;
        i = end;
      }
      out = sb;
    }
    return out;
  }
}

export class PoliceTermsV2 {
  private static readonly MIN_FUZZY_LEN: number = 4;
  private static readonly MIN_VAR_LEN: number = 5;
  private static readonly ID_DIGIT_SPACES: RegExp = new RegExp(
    '(身份证号|号码为|身份证号码为)[：:]?([0-9][0-9 ]{14,30})',
    'g'
  );
  private static readonly PLATE_CMD_COMPACT: RegExp = new RegExp(
    '((?:帮我)?(?:核查|查检)车牌号)[：:，,]?(川)([A-HJ-NP-Z])\\s*([A-HJ-NP-Z])\\s*([0-9]{5})',
    'g'
  );
  private static readonly WECOM_AFTER_YONG: RegExp = new RegExp(
    '用\\s*(v\\s*c+o+m+|we\\s*c+o+n*m+|微\\s*com|维康姆)\\s*(想|向)',
    'gi'
  );
  private static readonly WECOM_BEFORE_CALL: RegExp = new RegExp(
    '(v\\s*c+o+m+|we\\s*c+o+n*m+)(\\s*(?:向|发起呼叫))',
    'gi'
  );
  private terms: string[];
  private known: Set<string>;
  private homophones: TermsHomophones;
  private readingMap: TermReadingMap;

  constructor(context: common.Context) {
    const pairs = PoliceAssets.readCsvPairs(context, 'police_terms/term_homophones.csv');
    this.terms = PoliceAssets.uniqueByLengthDescending(
      PoliceAssets.readLines(context, 'police_terms/term_gazetteer.txt'));
    this.known = new Set<string>(this.terms);
    this.homophones = new TermsHomophones(pairs);
    this.readingMap = new TermReadingMap(pairs);
  }

  normalize(text: string): string {
    if (text.length === 0) return text;
    // 顺序对齐 Android：同音映射 → 短词护栏 → 情指行护栏 → 登录护栏 → 保守模糊层 → 电台音标数字。
    const global = this.homophones.apply(text);
    const shortGuarded = PoliceShortTermGuard.apply(global);
    const corrected = RadioDigits.normalize(
      this.fuzzyCorrect(
        DengluGuard.apply(QingZhiXingGuard.apply(shortGuarded))));
    return this.polish(corrected);
  }

  /** 管线末段润色；与 Android PoliceTermsNormalizerV2.polish 保持同序。 */
  polish(text: string): string {
    if (text.length === 0) return text;
    const formatted = this.formatVoiceCommands(text);
    return this.homophones.apply(formatted);
  }

  private formatVoiceCommands(text: string): string {
    let output = text;
    output = output.replace(
      PoliceTermsV2.ID_DIGIT_SPACES,
      (_match: string, prefix: string, digits: string): string =>
        `${prefix}：${digits.split(' ').join('')}`
    );
    output = output.replace(
      PoliceTermsV2.PLATE_CMD_COMPACT,
      (_match: string, prefix: string, province: string, city: string,
        serial: string, digits: string): string =>
        `${prefix}：${province}${city} ${serial}${digits}`
    );
    return this.normalizeWeComNames(output);
  }

  private normalizeWeComNames(text: string): string {
    let output = text.replace(PoliceTermsV2.WECOM_AFTER_YONG, '用WeCom向');
    output = output.replace(
      PoliceTermsV2.WECOM_BEFORE_CALL,
      (_match: string, _name: string, suffix: string): string => `WeCom${suffix}`
    );
    return output;
  }

  private maxSubsFor(length: number): number {
    return length >= 7 ? 2 : 1;
  }

  private fuzzyCorrect(text: string): string {
    let output = '';
    let i = 0;
    while (i < text.length) {
      const match = this.bestEqualLenAt(text, i) ?? this.bestVarLenAt(text, i);
      if (match === undefined) {
        output += text.charAt(i++);
      } else {
        output += match.term;
        i += match.consumed;
      }
    }
    return output;
  }

  private bestEqualLenAt(text: string, start: number): TermMatch | undefined {
    let best = '';
    let bestCost = Number.MAX_SAFE_INTEGER;
    let ambiguous = false;
    for (let i = 0; i < this.terms.length; i++) {
      const term = this.terms[i];
      const length = term.length;
      if (length < PoliceTermsV2.MIN_FUZZY_LEN) break;
      if (start + length > text.length) continue;
      const cost = this.subCost(text, start, term);
      if (cost < 0) continue;
      if (best.length === 0 || length > best.length) {
        best = term; bestCost = cost; ambiguous = false;
      } else if (length === best.length && cost < bestCost) {
        best = term; bestCost = cost; ambiguous = false;
      } else if (length === best.length && cost === bestCost && term !== best) {
        ambiguous = true;
      }
    }
    return best.length > 0 && !ambiguous ? new TermMatch(best, best.length) : undefined;
  }

  private bestVarLenAt(text: string, start: number): TermMatch | undefined {
    let best = '';
    let bestConsumed = 0;
    let bestCost = Number.MAX_SAFE_INTEGER;
    let ambiguous = false;
    for (let i = 0; i < this.terms.length; i++) {
      const term = this.terms[i];
      if (term.length < PoliceTermsV2.MIN_VAR_LEN) break;
      // 与 Android 对齐：只允许 raw 少 1 字（补字），不允许 len+1 吞掉句首/术语前的普通字。
      const width = term.length - 1;
      if (width < 1 || start + width > text.length) continue;
      const cost = this.varCost(text, start, term, width);
      if (cost < 0) continue;
      if (best.length === 0 || term.length > best.length) {
        best = term; bestConsumed = width; bestCost = cost; ambiguous = false;
      } else if (term.length === best.length && cost < bestCost) {
        best = term; bestConsumed = width; bestCost = cost; ambiguous = false;
      } else if (term.length === best.length && cost === bestCost &&
        (term !== best || width !== bestConsumed)) {
        ambiguous = true;
      }
    }
    return best.length > 0 && !ambiguous ? new TermMatch(best, bestConsumed) : undefined;
  }

  private subCost(text: string, start: number, term: string): number {
    const budget = this.maxSubsFor(term.length);
    let cost = 0;
    for (let i = 0; i < term.length; i++) {
      const from = text.charAt(start + i);
      const to = term.charAt(i);
      if (from === to) continue;
      if (!this.readingMap.allows(from, to)) return -1;
      if (++cost > budget) return -1;
    }
    return cost;
  }

  private varCost(text: string, start: number, term: string, width: number): number {
    const budget = this.maxSubsFor(term.length);
    const inf = budget + 1;
    let previous: number[] = [];
    for (let j = 0; j <= term.length; j++) previous.push(j);
    for (let i = 1; i <= width; i++) {
      const current: number[] = [i];
      const raw = text.charAt(start + i - 1);
      for (let j = 1; j <= term.length; j++) {
        const expected = term.charAt(j - 1);
        const substitution = raw === expected ? 0 : (this.readingMap.allows(raw, expected) ? 1 : inf);
        current.push(Math.min(inf, previous[j - 1] + substitution, previous[j] + 1, current[j - 1] + 1));
      }
      previous = current;
    }
    const cost = previous[term.length];
    return cost >= 1 && cost <= budget ? cost : -1;
  }
}
