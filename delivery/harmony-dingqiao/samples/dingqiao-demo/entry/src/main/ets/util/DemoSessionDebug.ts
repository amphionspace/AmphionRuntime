/** Bounded, JSON-safe diagnostics for one live capture plus an optional replay. */
export class DemoSessionDebug {
  private startedAtMs: number;
  private maxTraceEntries: number;
  private traceEntries: string[] = [];
  private droppedTraceEntries: number = 0;
  private voiceprintId: string = '';
  private voiceprintVerify: boolean = false;
  private speakerVad: boolean = false;
  private targetSpeakerEnhancement: boolean = false;
  private policeEnhancement: boolean = false;
  private audioFrames: number = 0;
  private audioBytes: number = 0;
  private resultCallbacks: number = 0;
  private partialResults: number = 0;
  private finalResults: number = 0;
  private lastResults: number = 0;
  private enhancedResults: number = 0;
  private lastSpeakerSimilarity?: number;
  private lastResultText: string = '';

  constructor(startedAtMs: number = Date.now(), maxTraceEntries: number = 200) {
    this.startedAtMs = startedAtMs;
    this.maxTraceEntries = Math.max(1, maxTraceEntries);
  }

  configure(
    voiceprintId: string,
    voiceprintVerify: boolean,
    speakerVad: boolean,
    targetSpeakerEnhancement: boolean,
    policeEnhancement: boolean,
    nowMs: number = Date.now()
  ): void {
    this.voiceprintId = voiceprintId;
    this.voiceprintVerify = voiceprintVerify;
    this.speakerVad = speakerVad;
    this.targetSpeakerEnhancement = targetSpeakerEnhancement;
    this.policeEnhancement = policeEnhancement;
    this.record('config', '',
      `voiceprint=${voiceprintId.length > 0 ? voiceprintId : 'none'}` +
      ` verify=${voiceprintVerify} speakerVad=${speakerVad}` +
      ` targetEnhancement=${targetSpeakerEnhancement} police=${policeEnhancement}`, nowMs);
  }

  record(stage: string, sessionId: string, detail: string, nowMs: number = Date.now()): void {
    const sid = sessionId.length > 0 ? ` | sid=${sessionId}` : '';
    const suffix = detail.length > 0 ? ` | ${detail}` : '';
    this.traceEntries.push(`[+${Math.max(0, nowMs - this.startedAtMs)}ms] ${stage}${sid}${suffix}`);
    if (this.traceEntries.length > this.maxTraceEntries) {
      this.traceEntries.shift();
      this.droppedTraceEntries += 1;
    }
  }

  addAudioFrame(byteCount: number, nowMs: number = Date.now()): void {
    this.audioFrames += 1;
    this.audioBytes += byteCount;
    if (this.audioFrames === 1 || this.audioFrames % 50 === 0) {
      this.record('audio', '',
        `frames=${this.audioFrames} bytes=${this.audioBytes} durationMs=${Math.round(this.audioBytes / 32)}`,
        nowMs);
    }
  }

  addResult(
    sessionId: string,
    text: string,
    isFinal: boolean,
    isLast: boolean,
    speakerSimilarity?: number,
    targetSpeakerEnhancementApplied: boolean = false,
    nowMs: number = Date.now()
  ): void {
    this.resultCallbacks += 1;
    if (isFinal) this.finalResults += 1;
    else this.partialResults += 1;
    if (isLast) this.lastResults += 1;
    if (targetSpeakerEnhancementApplied) this.enhancedResults += 1;
    if (speakerSimilarity !== undefined) this.lastSpeakerSimilarity = speakerSimilarity;
    const traceText = this.truncateText(text, 160);
    this.lastResultText = this.truncateText(text, 500);
    this.record(isFinal ? 'final' : 'partial', sessionId,
      `isLast=${isLast} text=${traceText}` +
      `${speakerSimilarity === undefined ? '' : ` similarity=${speakerSimilarity.toFixed(4)}`}` +
      ` enhanced=${targetSpeakerEnhancementApplied}`, nowMs);
  }

  audioFrameCount(): number {
    return this.audioFrames;
  }

  audioByteCount(): number {
    return this.audioBytes;
  }

  resultCallbackCount(): number {
    return this.resultCallbacks;
  }

  partialResultCount(): number {
    return this.partialResults;
  }

  summary(nowMs: number = Date.now()): string {
    return `增强=${this.targetSpeakerEnhancement ? '开' : '关'} · Speaker VAD=${this.speakerVad ? '开' : '关'}` +
      ` · 音频=${(this.audioBytes / 32000).toFixed(2)}s/${this.audioFrames}帧` +
      ` · 回调=${this.resultCallbacks}(final ${this.finalResults}, last ${this.lastResults})` +
      ` · 运行=${Math.max(0, nowMs - this.startedAtMs)}ms`;
  }

  traceText(): string {
    const dropped = this.droppedTraceEntries > 0 ?
      `[更早 ${this.droppedTraceEntries} 条已丢弃]\n` : '';
    return dropped + this.traceEntries.join('\n');
  }

  snapshot(nowMs: number = Date.now()): Record<string, Object> {
    const config: Record<string, Object> = {};
    config['voiceprintId'] = this.voiceprintId;
    config['voiceprintVerify'] = this.voiceprintVerify;
    config['speakerVad'] = this.speakerVad;
    config['targetSpeakerEnhancement'] = this.targetSpeakerEnhancement;
    config['policeEnhancement'] = this.policeEnhancement;
    const snapshot: Record<string, Object> = {};
    snapshot['startedAtEpochMs'] = this.startedAtMs;
    snapshot['elapsedMs'] = Math.max(0, nowMs - this.startedAtMs);
    snapshot['config'] = config;
    snapshot['audioFrames'] = this.audioFrames;
    snapshot['audioBytes'] = this.audioBytes;
    snapshot['audioDurationMs'] = Math.round(this.audioBytes / 32);
    snapshot['resultCallbacks'] = this.resultCallbacks;
    snapshot['partialResults'] = this.partialResults;
    snapshot['finalResults'] = this.finalResults;
    snapshot['lastResults'] = this.lastResults;
    snapshot['enhancedResults'] = this.enhancedResults;
    if (this.lastSpeakerSimilarity !== undefined) {
      snapshot['lastSpeakerSimilarity'] = this.lastSpeakerSimilarity;
    }
    snapshot['lastResultText'] = this.lastResultText;
    snapshot['trace'] = this.traceEntries.slice();
    snapshot['droppedTraceEntries'] = this.droppedTraceEntries;
    return snapshot;
  }

  private truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return `${text.substring(0, maxLength)}…(len=${text.length})`;
  }
}
