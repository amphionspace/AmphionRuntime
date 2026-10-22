import { http, webSocket } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { util } from '@kit.ArkTS';
import hilog from '@ohos.hilog';
import { RecognitionLanguage } from '../common/AppPrefs';
import { RecognizerEvents, TargetRecognizer } from './Recognizer';
import { SAMPLE_SLOTS, SampleSlot } from './VoiceprintSamples';

const TAG = 'AmphionCloud';
const STREAM_PATH = '/tuling/ast/v3';
const APP_ID = 'amphion-voice';
const HTTP_TIMEOUT_MS = 20000;
const CONNECT_TIMEOUT_MS = 8000;
// The server accepts any whole-sample chunk; 40 ms keeps message count low without adding latency.
const SEND_CHUNK_BYTES = 1280;
const MAX_PENDING_BYTES = 16000 * 2 * 10;

export class CloudEnrollmentStatus {
  /** true = usable, false = missing or needs re-registration, undefined = could not be determined. */
  available?: boolean;
  enrollmentId: string = '';
  reason: string = '';
}

interface ApiEnvelope {
  code?: number;
  message?: string;
  msg?: string;
  detail?: string;
  data?: Record<string, Object>;
}

// User-facing wording never names the server side; the page must not reveal which engine is in use.
// The raw BusinessError goes to hilog (public) so on-device failures can be diagnosed.
function readableError(e: Object): string {
  const err = e as BusinessError;
  hilog.error(0x0000, TAG, 'request failed code=%{public}d message=%{public}s', err.code ?? -1, err.message ?? '');
  const code = err.code !== undefined ? `（${err.code}）` : '';
  if (err.code === 2300028 || err.code === 2300007 || err.code === 2300006) return `无法连接识别服务${code}`;
  if (err.code === 2300060 || err.code === 2300035) return `无法建立安全连接${code}`;
  return `识别服务请求失败${code}`;
}

function parseEnvelope(raw: string | Object | ArrayBuffer): ApiEnvelope {
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as ApiEnvelope;
    } catch (_e) {
      return { code: -1, message: '服务返回格式异常' };
    }
  }
  return raw as ApiEnvelope;
}

function envelopeMessage(body: ApiEnvelope, fallback: string): string {
  return body.detail ?? body.message ?? body.msg ?? fallback;
}

/** Server rejection reasons shown to the user in Chinese; the raw text stays in hilog. */
function enrollmentRejection(body: ApiEnvelope): string {
  const code = `${body.code ?? ''}`;
  if (code === 'too_short') return '录音中说话声太少，请重新录制';
  if (code === 'too_noisy' || code === 'low_quality') return '录音杂音太大，请在安静处重新录制';
  return '声纹注册失败，请稍后重试';
}

/** Voiceprint management against the private cloud deployment. */
export class CloudVoiceprint {
  private readonly base: string;
  private readonly profileKey: string;

  constructor(base: string, profileKey: string) {
    this.base = base;
    this.profileKey = profileKey;
  }

  async register(paths: Record<string, string>): Promise<string> {
    const forms: http.MultiFormData[] = SAMPLE_SLOTS.map((slot: SampleSlot): http.MultiFormData => {
      const item: http.MultiFormData = {
        name: `audio_${slot}`,
        contentType: 'audio/wav',
        remoteFileName: `voiceprint-${slot}.wav`,
        filePath: paths[slot]
      };
      return item;
    });
    const client = http.createHttp();
    try {
      const response = await client.request(`${this.base}/api/asr/enrollment`, {
        method: http.RequestMethod.POST,
        header: this.headers('multipart/form-data'),
        multiFormDataList: forms,
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: HTTP_TIMEOUT_MS,
        readTimeout: HTTP_TIMEOUT_MS * 3
      });
      const body = parseEnvelope(response.result);
      const id = body.data !== undefined ? `${body.data['enrollmentId'] ?? ''}` : '';
      if (response.responseCode !== 200 || Number(body.code) !== 0 || id.length === 0) {
        hilog.error(0x0000, TAG, 'register http=%{public}d code=%{public}s message=%{public}s', response.responseCode,
          `${body.code ?? ''}`, envelopeMessage(body, ''));
        throw new Error(enrollmentRejection(body));
      }
      return id;
    } catch (e) {
      if (e instanceof Error) throw e;
      throw new Error(readableError(e as Object));
    } finally {
      client.destroy();
    }
  }

  async status(): Promise<CloudEnrollmentStatus> {
    const result = new CloudEnrollmentStatus();
    const client = http.createHttp();
    try {
      const response = await client.request(`${this.base}/api/asr/enrollment/status`, {
        method: http.RequestMethod.GET,
        header: this.headers('application/json'),
        expectDataType: http.HttpDataType.STRING,
        connectTimeout: HTTP_TIMEOUT_MS,
        readTimeout: HTTP_TIMEOUT_MS
      });
      const body = parseEnvelope(response.result);
      const data = body.data;
      if (response.responseCode === 200 && data !== undefined) {
        const available = data['available'];
        result.available = available === true ? true : (available === false ? false : undefined);
        result.enrollmentId = `${data['enrollmentId'] ?? ''}`;
        result.reason = `${data['reason'] ?? ''}`;
      }
    } catch (e) {
      hilog.warn(0x0000, TAG, 'status: %{public}s', readableError(e as Object));
    } finally {
      client.destroy();
    }
    return result;
  }

  async remove(enrollmentId: string): Promise<void> {
    if (enrollmentId.length === 0) return;
    const client = http.createHttp();
    try {
      const response = await client.request(
        `${this.base}/api/asr/enrollment/${encodeURIComponent(enrollmentId)}`, {
          method: http.RequestMethod.DELETE,
          header: this.headers('application/json'),
          expectDataType: http.HttpDataType.STRING,
          connectTimeout: HTTP_TIMEOUT_MS,
          readTimeout: HTTP_TIMEOUT_MS
        });
      if (response.responseCode !== 200 && response.responseCode !== 404) {
        throw new Error(envelopeMessage(parseEnvelope(response.result), '声纹删除失败'));
      }
    } catch (e) {
      if (e instanceof Error) throw e;
      throw new Error(readableError(e as Object));
    } finally {
      client.destroy();
    }
  }

  private headers(contentType: string): Record<string, string> {
    const header: Record<string, string> = {};
    header['Content-Type'] = contentType;
    header['X-Voiceprint-Key'] = this.profileKey;
    header['X-ASR-Debugger'] = '1';
    return header;
  }
}

interface WordItem {
  w?: string;
}

interface WsItem {
  cw?: WordItem[];
}

interface AudioRange {
  start_sample?: number;
  end_sample?: number;
}

interface StreamResult {
  msgtype?: string;
  segId?: number;
  audio_range?: AudioRange;
  ws?: WsItem[];
  ls?: boolean;
  fallback_text?: string;
}

class SegmentPreview {
  start: number;
  text: string;

  constructor(start: number, text: string) {
    this.start = start;
    this.text = text;
  }
}

interface StreamHeader {
  code?: number;
  message?: string;
  status?: number;
}

interface StreamMessage {
  header?: StreamHeader;
  payload?: Record<string, StreamResult>;
}

/** Cloud session over the AST v3 stream with owner (target-speaker) filtering and Speaker VAD. */
export class CloudRecognizer implements TargetRecognizer {
  private readonly base: string;
  private readonly enrollmentId: string;
  private readonly language: RecognitionLanguage;
  private readonly traceId: string;
  private events?: RecognizerEvents;
  private ws?: webSocket.WebSocket;
  private open: boolean = false;
  private finishRequested: boolean = false;
  private closed: boolean = false;
  private pending: Uint8Array[] = [];
  private pendingBytes: number = 0;
  private chunk: Uint8Array = new Uint8Array(SEND_CHUNK_BYTES);
  private chunkFill: number = 0;
  private base64: util.Base64Helper = new util.Base64Helper();
  private connectTimer: number = -1;
  // Latest preview per segment not yet finalized. With an enrollment, finals lag and the next
  // segment's previews can arrive before the previous sentence; the live row shows the oldest one.
  private previews: Map<number, SegmentPreview> = new Map<number, SegmentPreview>();
  private sendChain: Promise<void> = Promise.resolve();

  private readonly speakerVad: boolean;

  /** speakerVad=false leaves enable_speaker_vad out of the start frame entirely. */
  constructor(base: string, enrollmentId: string, language: RecognitionLanguage, speakerVad: boolean = true) {
    this.speakerVad = speakerVad;
    this.base = base;
    this.enrollmentId = enrollmentId;
    this.language = language;
    this.traceId = `amphion-${Date.now().toString(36)}-${Math.floor(Math.random() * 0xffffff).toString(16)}`;
  }

  start(events: RecognizerEvents): void {
    this.events = events;
    const ws = webSocket.createWebSocket();
    this.ws = ws;
    ws.on('open', (): void => {
      if (this.closed) return;
      clearTimeout(this.connectTimer);
      this.open = true;
      this.sendJson(this.startFrame());
      const buffered = this.pending;
      this.pending = [];
      this.pendingBytes = 0;
      buffered.forEach((bytes: Uint8Array): void => this.sendAudio(bytes));
      this.events?.onListening();
      if (this.finishRequested) this.sendEnd();
    });
    ws.on('message', (_err: BusinessError, value: string | ArrayBuffer): void => {
      if (typeof value === 'string') this.handleMessage(value);
    });
    ws.on('close', (_err: BusinessError, info: webSocket.CloseResult): void => {
      if (this.closed) return;
      hilog.warn(0x0000, TAG, 'closed %{public}d %{public}s', info.code, info.reason);
      if (this.finishRequested) this.complete();
      else this.fail('识别连接已断开');
    });
    ws.on('error', (err: BusinessError): void => {
      if (this.closed) return;
      hilog.error(0x0000, TAG, 'socket error %{public}d %{public}s', err.code, err.message);
      this.fail(this.open ? '识别连接异常中断' : '无法连接识别服务');
    });
    const target = `${this.base.replace(/^http/, 'ws')}${STREAM_PATH}`;
    this.connectTimer = setTimeout((): void => {
      if (!this.open && !this.closed) this.fail('识别连接超时');
    }, CONNECT_TIMEOUT_MS);
    ws.connect(target).catch((e: BusinessError): void => {
      if (!this.closed) this.fail(readableError(e));
    });
  }

  write(frame: ArrayBuffer): void {
    if (this.closed || this.finishRequested) return;
    const bytes = new Uint8Array(frame);
    let offset = 0;
    while (offset < bytes.length) {
      const take = Math.min(SEND_CHUNK_BYTES - this.chunkFill, bytes.length - offset);
      this.chunk.set(bytes.subarray(offset, offset + take), this.chunkFill);
      this.chunkFill += take;
      offset += take;
      if (this.chunkFill === SEND_CHUNK_BYTES) this.flushChunk();
    }
  }

  finish(): void {
    if (this.closed || this.finishRequested) return;
    this.flushChunk();
    this.finishRequested = true;
    if (this.open) this.sendEnd();
  }

  cancel(): void {
    if (this.closed) return;
    this.closed = true;
    this.shutdownSocket();
  }

  private flushChunk(): void {
    if (this.chunkFill === 0) return;
    const bytes = this.chunk.slice(0, this.chunkFill);
    this.chunkFill = 0;
    if (!this.open) {
      if (this.pendingBytes + bytes.length <= MAX_PENDING_BYTES) {
        this.pending.push(bytes);
        this.pendingBytes += bytes.length;
      }
      return;
    }
    this.sendAudio(bytes);
  }

  private sendAudio(bytes: Uint8Array): void {
    const audio: Record<string, Object> = { 'audio': this.base64.encodeToStringSync(bytes) };
    const payload: Record<string, Object> = { 'audio': audio };
    const frame: Record<string, Object> = { 'header': this.header(1), 'payload': payload };
    this.sendJson(frame);
  }

  private sendEnd(): void {
    const frame: Record<string, Object> = { 'header': this.header(2) };
    this.sendJson(frame);
  }

  private header(status: number): Record<string, Object> {
    const header: Record<string, Object> = {
      'traceId': this.traceId, 'appId': APP_ID, 'bizId': this.traceId, 'status': status
    };
    return header;
  }

  private startFrame(): Record<string, Object> {
    const config: Record<string, Object> = {
      'silence_duration_ms': 1200,
      'vad_start_frames': 20,
      'vad_threshold': 0.45,
      'endpoint_max_utterance_ms': 20000,
      'language': this.language,
      'enable_pseudo_stream': true,
      'enable_role_separation': false,
      'enrollment_enable': true,
      'enrollment_id': this.enrollmentId,
      'enable_debug_capture': false
    };
    if (this.speakerVad) config['enable_speaker_vad'] = true;
    const parameter: Record<string, Object> = { 'asr_config': config };
    const frame: Record<string, Object> = { 'header': this.header(0), 'parameter': parameter };
    return frame;
  }

  /**
   * Frames are sent strictly one after another. WebSocket.send is asynchronous and concurrent calls
   * are not guaranteed to leave in call order; the server rejects a session whose first frame is
   * audio instead of the start frame (seen on device as "the first AST frame must have status=0").
   */
  private sendJson(frame: Record<string, Object>): void {
    const data = JSON.stringify(frame);
    this.sendChain = this.sendChain.then(async (): Promise<void> => {
      const ws = this.ws;
      if (ws === undefined || this.closed) return;
      try {
        await ws.send(data);
      } catch (e) {
        hilog.warn(0x0000, TAG, 'send failed: %{public}s', (e as BusinessError).message);
      }
    });
  }

  private handleMessage(raw: string): void {
    if (this.closed) return;
    let message: StreamMessage;
    try {
      message = JSON.parse(raw) as StreamMessage;
    } catch (_e) {
      return;
    }
    const header = message.header ?? {};
    const result: StreamResult = message.payload?.['result'] ?? {};
    if (Number(header.code ?? 0) !== 0) {
      hilog.error(0x0000, TAG, 'server error %{public}d %{public}s', Number(header.code), header.message ?? '');
      this.fail('识别失败，请稍后重试');
      return;
    }
    const kind = (result.msgtype ?? '').toLowerCase();
    const text = kind === 'segment_error' ? (result.fallback_text ?? '') : this.extractText(result);
    const seg = result.segId ?? 0;
    if (kind === 'progressive') {
      // With an enrollment every preview already comes from the target-speaker model, so it is shown
      // at once. speech_started is not a per-segment confirmation (its segId is "last sentence + 1"),
      // so previews are not gated on it.
      const start = result.audio_range?.start_sample ?? -1;
      const shown = this.oldestPreview();
      const before = this.previews.get(seg);
      this.previews.set(seg, new SegmentPreview(start, text));
      if (shown !== undefined && seg !== shown) return;
      // The same segment restarting elsewhere means the server dropped the earlier span (someone else).
      if (before !== undefined && start >= 0 && before.start >= 0 && start !== before.start) this.events?.onFiltered();
      this.events?.onPartial(text);
    } else if (kind === 'sentence' || kind === 'segment_error') {
      this.previews.delete(seg);
      // An empty owner sentence retracts a span spoken by someone else.
      if (text.length > 0) {
        this.events?.onFinal(text, undefined, result.audio_range?.start_sample, result.audio_range?.end_sample);
      }
      else if (kind === 'sentence' && !(Number(header.status) === 2 || result.ls === true)) this.events?.onFiltered();
      else this.events?.onPartial('');
      // The next segment may already be previewing; continue the live row with it right away.
      const next = this.oldestPreview();
      if (next !== undefined) this.events?.onPartial((this.previews.get(next) as SegmentPreview).text);
    }
    if (Number(header.status) === 2 || result.ls === true) this.complete();
  }

  private oldestPreview(): number | undefined {
    let oldest: number | undefined = undefined;
    this.previews.forEach((_p: SegmentPreview, seg: number): void => {
      if (oldest === undefined || seg < oldest) oldest = seg;
    });
    return oldest;
  }

  private extractText(result: StreamResult): string {
    let text = '';
    (result.ws ?? []).forEach((item: WsItem): void => {
      (item.cw ?? []).forEach((word: WordItem): void => {
        text += word.w ?? '';
      });
    });
    return text;
  }

  private complete(): void {
    if (this.closed) return;
    this.closed = true;
    this.shutdownSocket();
    this.events?.onComplete();
  }

  private fail(message: string): void {
    if (this.closed) return;
    this.closed = true;
    this.shutdownSocket();
    this.events?.onError(message);
  }

  private shutdownSocket(): void {
    clearTimeout(this.connectTimer);
    const ws = this.ws;
    this.ws = undefined;
    if (ws === undefined) return;
    try {
      ws.off('open');
      ws.off('message');
      ws.off('close');
      ws.off('error');
      ws.close().catch((): void => {});
    } catch (_e) {
    }
  }
}
