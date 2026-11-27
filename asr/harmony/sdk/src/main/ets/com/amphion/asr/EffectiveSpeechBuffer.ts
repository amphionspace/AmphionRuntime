export const ACOUSTIC_WINDOWS_PER_SECOND: number = 50;
export const ACOUSTIC_ACTIVE_RMS_THRESHOLD: number = 0.01;
export const MIN_SPEECH_ZERO_CROSSING_RATE: number = 0.005;
export const MAX_SPEECH_ZERO_CROSSING_RATE: number = 0.35;
export const REQUIRED_SPEECH_LIKE_WINDOWS: number = 3;
export const MIN_SPEECH_ENERGY_RATIO: number = 3;
/**
 * 决定"非空文本能不能发布"的 20 ms 窗 RMS 下限，约 -74 dBFS。与安卓
 * EffectiveSpeechBuffer.PUBLISH_RMS_THRESHOLD 必须一致。
 *
 * 安全带是实测出来的，两头都有余量：
 * - 上沿 -54 dBFS（0.002）：再高就开始丢真实远场语音；-40 dBFS 时丢 13.3%
 *   （丁桥 12/90、AISHELL-3 61/500）。
 * - 下沿 -89.9 dBFS：客户复现音频里那段近似数字静音的**最大**窗 RMS，阈值高于它才拦得住。
 *
 * 已知限制：丁桥现场 204 段真实房间静音的最大窗 RMS 中位 -24.4 dBFS、最低 -44.2 dBFS，
 * 远在安全带之上。所以这道门禁挡的是近似数字静音，**挡不住普通房间噪声里的幻觉**。
 */
export const PUBLISH_RMS_THRESHOLD: number = 0.0002;
/**
 * 只由填充词构成的文本（"嗯""呃""啊"…）在没有原生 VAD 语音证据时不发布（客户 #92）。
 *
 * 真机实测（Mate 80，0.3.29）：真人声之后接 −40～−70 dBFS 的粉噪，57 s 内会出 1～4 个"嗯。/呃。"，
 * 全部是 VAD 没判出语音、由原生 rule2 端点吐出的单字；它们能过上面那条 −74 dBFS 的声学门禁，
 * 因为普通底噪电平远在其上（已知限制）。填充词是识别器在无语音输入时最常见的幻觉形态，
 * 而真人说出的"嗯"在 Silero（阈值 0.5、窗 512、minSpeechDuration 0.25 s）下会被判成语音
 * （客户同一录音里 3～5 s 的真人"嗯"走的就是 vad-active 端点）。所以只对"填充词 + 无 VAD 语音"
 * 收紧，不动有实词的文本，也不另设字数或时长门槛。两端规则一致。
 */
export const FILLER_ONLY_CHARS: string = '嗯呃额啊哦噢喔唔诶欸哎唉呀哼嘶';
export const FILLER_ONLY_MAX_CHARS: number = 4;
const FILLER_ONLY_WORDS: string[] = ['um', 'uh', 'uhm', 'hmm', 'hm', 'mm', 'mmm', 'ah', 'oh', 'eh', 'er'];
export const SUPPRESS_REASON_FILLER_WITHOUT_VAD: string = 'filler-without-vad';
export const SUPPRESS_REASON_NO_INDEPENDENT_EVIDENCE: string = 'effective-speech-boundary';

/** 去掉空白与标点后，是否只剩填充词（见 FILLER_ONLY_CHARS）。空文本返回 false。 */
export function isFillerOnlyText(text: string): boolean {
  let core = '';
  for (const ch of text) {
    if (/[\s\p{P}\p{S}]/u.test(ch)) continue;
    core += ch;
  }
  if (core.length === 0) return false;
  const lower = core.toLowerCase();
  if (FILLER_ONLY_WORDS.indexOf(lower) >= 0) return true;
  if (core.length > FILLER_ONLY_MAX_CHARS) return false;
  for (const ch of core) {
    if (FILLER_ONLY_CHARS.indexOf(ch) < 0) return false;
  }
  return true;
}
const MIN_EDGE_SILENCE_MS: number = 5;
const MAX_EDGE_SILENCE_AMPLITUDE: number = ACOUSTIC_ACTIVE_RMS_THRESHOLD / 2;
const MAX_VAD_EVIDENCE_LAG_WINDOWS: number = 3;

class EffectiveSpeechRun {
  parts: Float32Array[] = [];
  sampleCount: number = 0;
  windowCount: number = 0;
  acousticallyConfirmed: boolean = false;
  externallyConfirmed: boolean = false;
  // 同 acousticallyConfirmed，但用低得多的 PUBLISH_RMS_THRESHOLD；只管文本能否发布，
  // 不参与说话人打分的样本选取。
  publishSupported: boolean = false;
  // 原生 VAD 确认过这个 run。与 externallyConfirmed 的区别是来源：后者也会被
  // asrSpeechConfirmed 置真，而那来自识别器自己，拿它验证识别器的文本是循环论证。
  vadConfirmed: boolean = false;
}

export class EffectiveSpeechFinalDecision {
  publish: boolean;
  samples: Float32Array;
  /** publish=false 时的原因，供 RESULT_SUPPRESSED 指标区分来源；publish=true 时为空串。 */
  reason: string;

  constructor(publish: boolean, samples: Float32Array, reason: string = '') {
    this.publish = publish;
    this.samples = samples;
    this.reason = reason;
  }
}

export function acousticRms(squareSum: number, sampleCount: number): number {
  return sampleCount > 0 ? Math.sqrt(squareSum / sampleCount) : 0;
}

export function isAcousticallyActive(rms: number): boolean {
  return rms >= ACOUSTIC_ACTIVE_RMS_THRESHOLD;
}

export function isSpeechShapedWindow(rms: number, zeroCrossingRate: number): boolean {
  return isAcousticallyActive(rms) &&
    zeroCrossingRate >= MIN_SPEECH_ZERO_CROSSING_RATE &&
    zeroCrossingRate <= MAX_SPEECH_ZERO_CROSSING_RATE;
}

// Selects speech-shaped 20 ms windows for final speaker scoring. Native VAD or ASR evidence admits
// a scale-invariant low-volume or constant-envelope run. Evidence stays bound to that contiguous run,
// while the acoustic-only fallback still requires both envelope movement and speech-shaped energy.
export class EffectiveSpeechBuffer {
  private window: Float32Array;
  private samplesInWindow: number = 0;
  private runs: EffectiveSpeechRun[] = [];
  private currentRun?: EffectiveSpeechRun;
  private latestRun?: EffectiveSpeechRun;
  private retainedSamples: number = 0;
  private pendingEvidenceWindows: number = 0;
  private windowsSinceLatestRun: number = Number.MAX_SAFE_INTEGER;
  private acousticRunWindows: number = 0;
  private acousticRunMinRms: number = Number.MAX_VALUE;
  private acousticRunMaxRms: number = 0;
  // 自上次 reset 以来处理过的 20 ms 窗数。区分"没喂过音频"与"喂过但没有独立证据"。
  private processedWindows: number = 0;
  private publishRunWindows: number = 0;
  private publishRunMinRms: number = Number.MAX_VALUE;
  private publishRunMaxRms: number = 0;
  private maxSamples: number;
  private minEdgeSilenceSamples: number;

  constructor(sampleRate: number, maxSamples: number) {
    const windowSamples = Math.max(1, Math.round(sampleRate / ACOUSTIC_WINDOWS_PER_SECOND));
    this.window = new Float32Array(windowSamples);
    this.maxSamples = Math.max(0, Math.round(maxSamples));
    this.minEdgeSilenceSamples = Math.max(1, Math.round(sampleRate * MIN_EDGE_SILENCE_MS / 1000));
  }

  observe(samples: Float32Array): void {
    let offset = 0;
    while (offset < samples.length) {
      const count = Math.min(samples.length - offset, this.window.length - this.samplesInWindow);
      this.window.set(samples.slice(offset, offset + count), this.samplesInWindow);
      this.samplesInWindow += count;
      offset += count;
      if (this.samplesInWindow === this.window.length) {
        this.processWindow(this.window.slice());
        this.samplesInWindow = 0;
      }
    }
  }

  // VAD evidence normally arrives after observe() for the same native window. A bounded lag accepts
  // detector latency without allowing evidence to reach across a real gap into an older candidate.
  confirmSpeech(): void {
    const run = this.currentRun ??
      (this.windowsSinceLatestRun <= MAX_VAD_EVIDENCE_LAG_WINDOWS ? this.latestRun : undefined);
    if (run !== undefined) {
      run.externallyConfirmed = true;
      run.vadConfirmed = true;
    } else {
      this.pendingEvidenceWindows = MAX_VAD_EVIDENCE_LAG_WINDOWS;
    }
  }

  // ASR text/token evidence belongs to the latest candidate preceding the final, even when trailing
  // silence has already closed that run. Other runs still need their own evidence or envelope change.
  take(asrSpeechConfirmed: boolean = false): Float32Array {
    this.confirmLatestRun(asrSpeechConfirmed);
    const output = this.collectConfirmedRuns();
    this.reset();
    return output;
  }

  // A token-only endpoint is recognizer evidence, not a public utterance boundary. Keep its audio for
  // the next result with public text. A terminal result consumes confirmed effective speech even when
  // text is empty: speaker-score availability depends on usable speech duration, not ASR text quality.
  resolveFinal(publicText: string, asrSpeechConfirmed: boolean,
    isLast: boolean): EffectiveSpeechFinalDecision {
    if (publicText.length === 0) {
      if (!isLast) {
        this.confirmLatestRun(asrSpeechConfirmed);
        return new EffectiveSpeechFinalDecision(false, new Float32Array(0));
      }
      return new EffectiveSpeechFinalDecision(true, this.take(asrSpeechConfirmed));
    }
    // 非空文本必须有**独立于识别器**的证据才发布。识别器在真人声之后的长静音里会吐出
    // 零散短 token（实测：同一段近似数字静音，前面放 3 秒真人声就出，前面放数字零就九个
    // 电平全不出），而 asrSpeechConfirmed 来自识别器自己，用它验证识别器的文本是循环论证。
    // 这里不调 confirmLatestRun：既然判定这段文本没有独立证据，就不该让它把这个 run 变成
    // 说话人打分的素材。
    // processedWindows === 0 表示自上次 reset 以来一个窗都没喂过：这时没有判据，而且那段
    // 音频已经在上一次 terminal final 里发布过了，保持原行为放行。幻觉场景不会落到这里，
    // 因为运行时是持续喂音频的（哪怕是近似数字静音，也会产生窗和 run）。
    // 被门禁拦下的非空 final 也是一句话的结束：清掉这一句保留的 run，否则长时间底噪里一句
    // 接一句被拦，run 与 PCM 会一直累到 UTT_MAX_SAMPLES 上限，之后窗证据停止更新，且早先
    // 的 VAD 证据会被下一句继承。
    if (this.processedWindows > 0 && !this.hasIndependentSpeechEvidence()) {
      this.reset();
      return new EffectiveSpeechFinalDecision(false, new Float32Array(0),
        SUPPRESS_REASON_NO_INDEPENDENT_EVIDENCE);
    }
    // 只有填充词、且原生 VAD 全程没判出语音：普通底噪能过声学门禁（见 FILLER_ONLY_CHARS 注释），
    // 这里要求独立于识别器且独立于能量的第二个信号。
    if (this.processedWindows > 0 && isFillerOnlyText(publicText) && !this.hasVadSpeechEvidence()) {
      this.reset();
      return new EffectiveSpeechFinalDecision(false, new Float32Array(0),
        SUPPRESS_REASON_FILLER_WITHOUT_VAD);
    }
    return new EffectiveSpeechFinalDecision(true, this.take(asrSpeechConfirmed));
  }

  /** 原生 VAD 是否确认过本句里的任一 run（不看窗数：真人"嗯"可能只有十几个窗）。 */
  hasVadSpeechEvidence(): boolean {
    return this.runs.some((run: EffectiveSpeechRun): boolean => run.vadConfirmed);
  }

  // 是否存在独立于识别器的语音证据：按 PUBLISH_RMS_THRESHOLD 确认的声学 run，或原生 VAD
  // 确认过的 run。保留 VAD 这一支是因为低音量、恒定包络的真实语音过不了包络起伏那一关，
  // 而 VAD 是独立信号：实测 Silero（阈值 0.5、窗 512）在客户那段 42.2 秒近似静音上判出
  // 0 段，在同一文件的真人声上判出 1.38 秒。
  hasIndependentSpeechEvidence(): boolean {
    return this.runs.some((run: EffectiveSpeechRun): boolean =>
      run.windowCount >= REQUIRED_SPEECH_LIKE_WINDOWS &&
      (run.publishSupported || run.vadConfirmed));
  }

  reset(): void {
    this.samplesInWindow = 0;
    this.runs = [];
    this.currentRun = undefined;
    this.latestRun = undefined;
    this.retainedSamples = 0;
    this.pendingEvidenceWindows = 0;
    this.windowsSinceLatestRun = Number.MAX_SAFE_INTEGER;
    this.processedWindows = 0;
    this.resetAcousticRun();
    this.resetPublishRun();
  }

  private processWindow(samples: Float32Array): void {
    this.processedWindows += 1;
    if (this.pendingEvidenceWindows > 0) this.pendingEvidenceWindows -= 1;
    // The sample cap is also the metadata cap. Without this early return, an utterance that never
    // endpoints could keep allocating empty run objects after the retained audio reached 25 seconds.
    if (this.retainedSamples >= this.maxSamples) return;
    let squareSum = 0;
    let zeroCrossings = 0;
    for (let i = 0; i < samples.length; i++) {
      squareSum += samples[i] * samples[i];
      if (i > 0 && (samples[i] >= 0) !== (samples[i - 1] >= 0)) zeroCrossings += 1;
    }
    const rms = acousticRms(squareSum, samples.length);
    const zcr = zeroCrossings / Math.max(1, samples.length - 1);
    const evidenceCandidate = rms > 0 &&
      zcr >= MIN_SPEECH_ZERO_CROSSING_RATE && zcr <= MAX_SPEECH_ZERO_CROSSING_RATE;
    if (!evidenceCandidate) {
      this.currentRun = undefined;
      this.resetAcousticRun();
      this.resetPublishRun();
      if (this.windowsSinceLatestRun !== Number.MAX_SAFE_INTEGER) {
        this.windowsSinceLatestRun += 1;
      }
      return;
    }

    const edgeSilenceAmplitude = Math.min(MAX_EDGE_SILENCE_AMPLITUDE, rms / 4);
    const effectiveSamples = this.trimLongSilentEdges(samples, edgeSilenceAmplitude);
    if (this.currentRun === undefined) {
      const run = new EffectiveSpeechRun();
      if (this.pendingEvidenceWindows > 0) {
        // pendingEvidenceWindows 只由 confirmSpeech() 设置，所以这也是 VAD 来源的证据
        run.externallyConfirmed = true;
        run.vadConfirmed = true;
        this.pendingEvidenceWindows = 0;
      }
      this.runs.push(run);
      this.currentRun = run;
      this.latestRun = run;
    }
    this.appendToRun(this.currentRun, effectiveSamples);
    this.currentRun.windowCount += 1;
    this.windowsSinceLatestRun = 0;

    // 发布支撑的判定必须在下面那个 0.01 的提前返回之前做，否则低于 0.01 的窗就被跳过了。
    // 走到这里 ZCR 已经在区间内，所以只需再比阈值。连续窗数与包络比沿用同一组常量。
    if (rms >= PUBLISH_RMS_THRESHOLD) {
      this.publishRunWindows += 1;
      this.publishRunMinRms = Math.min(this.publishRunMinRms, rms);
      this.publishRunMaxRms = Math.max(this.publishRunMaxRms, rms);
      if (this.publishRunWindows >= REQUIRED_SPEECH_LIKE_WINDOWS &&
        this.publishRunMaxRms >= this.publishRunMinRms * MIN_SPEECH_ENERGY_RATIO) {
        this.currentRun.publishSupported = true;
      }
    } else {
      this.resetPublishRun();
    }

    if (!isSpeechShapedWindow(rms, zcr)) {
      this.resetAcousticRun();
      return;
    }
    this.acousticRunWindows += 1;
    this.acousticRunMinRms = Math.min(this.acousticRunMinRms, rms);
    this.acousticRunMaxRms = Math.max(this.acousticRunMaxRms, rms);
    if (this.acousticRunWindows >= REQUIRED_SPEECH_LIKE_WINDOWS &&
      this.acousticRunMaxRms >= this.acousticRunMinRms * MIN_SPEECH_ENERGY_RATIO) {
      this.currentRun.acousticallyConfirmed = true;
    }
  }

  private appendToRun(run: EffectiveSpeechRun, samples: Float32Array): void {
    const remaining = this.maxSamples - this.retainedSamples;
    if (remaining <= 0) return;
    const retained = samples.length <= remaining ? samples : samples.slice(0, remaining);
    run.parts.push(retained);
    run.sampleCount += retained.length;
    this.retainedSamples += retained.length;
  }

  private collectConfirmedRuns(): Float32Array {
    const parts: Float32Array[] = [];
    let total = 0;
    for (let i = 0; i < this.runs.length; i++) {
      const run = this.runs[i];
      if (run.windowCount < REQUIRED_SPEECH_LIKE_WINDOWS) continue;
      if (!run.externallyConfirmed && !run.acousticallyConfirmed) continue;
      for (let j = 0; j < run.parts.length; j++) parts.push(run.parts[j]);
      total += run.sampleCount;
    }
    return concatSamples(parts, total);
  }

  private confirmLatestRun(confirmed: boolean): void {
    if (confirmed && this.latestRun !== undefined) {
      this.latestRun.externallyConfirmed = true;
    }
  }

  // A speech-shaped window can straddle the true start/end of an utterance. Remove only a sustained
  // quiet edge (at least 5 ms) after the multi-signal window has been accepted; individual zero
  // crossings inside voiced audio are retained and cannot shorten an otherwise valid 1.5 s segment.
  private trimLongSilentEdges(samples: Float32Array, silenceAmplitude: number): Float32Array {
    let start = 0;
    while (start < samples.length && Math.abs(samples[start]) < silenceAmplitude) start += 1;
    if (start < this.minEdgeSilenceSamples) start = 0;

    let end = samples.length;
    while (end > start && Math.abs(samples[end - 1]) < silenceAmplitude) end -= 1;
    if (samples.length - end < this.minEdgeSilenceSamples) end = samples.length;
    return start === 0 && end === samples.length ? samples : samples.slice(start, end);
  }

  private resetPublishRun(): void {
    this.publishRunWindows = 0;
    this.publishRunMinRms = Number.MAX_VALUE;
    this.publishRunMaxRms = 0;
  }

  private resetAcousticRun(): void {
    this.acousticRunWindows = 0;
    this.acousticRunMinRms = Number.MAX_VALUE;
    this.acousticRunMaxRms = 0;
  }
}

function concatSamples(parts: Float32Array[], total: number): Float32Array {
  const output = new Float32Array(total);
  let offset = 0;
  for (let i = 0; i < parts.length; i++) {
    output.set(parts[i], offset);
    offset += parts[i].length;
  }
  return output;
}
