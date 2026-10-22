import { abilityAccessCtrl, bundleManager, common, Permissions } from '@kit.AbilityKit';
import { promptAction } from '@kit.ArkUI';
import hilog from '@ohos.hilog';
import { AppPrefs, VoiceprintProfile, EngineKind, RecognitionLanguage } from '../common/AppPrefs';
import { Motion, Palette, Space } from '../common/Theme';
import { LevelBars } from '../components/LevelBars';
import { CloudRecognizer, CloudVoiceprint, CloudEnrollmentStatus } from '../services/CloudService';
import { LocalEngine, LocalRecognizer, LocalState } from '../services/LocalEngine';
import { RecognizerEvents, TargetRecognizer } from '../services/Recognizer';
import {
  SAMPLE_MAX_SEC,
  SAMPLE_MIN_SEC,
  SAMPLE_SLOTS,
  SampleInfo,
  SampleSlot,
  VOICED_MIN_SEC,
  VoiceprintSamples,
  slotHint,
  slotLabel,
  voicedSeconds
} from '../services/VoiceprintSamples';
import { AudioRecorder } from '../util/AudioRecorder';
import { PcmFrameWriter } from '../util/PcmFrameWriter';
import { PcmPlayer } from '../util/PcmPlayer';
import { SmoothText } from '../util/SmoothText';
import { DebugSession } from '../util/DebugSession';
import { SentenceClips } from '../util/SentenceClips';

const LEVEL_BARS = 28;
const LEVEL_TICK_MS = 66;

/** Reading prompts shown while recording a sample; natural sentences give the extractor varied phonemes. */
const SLOT_PROMPTS: Record<string, string> = {
  'far': '今天的天气不错，我打算下午去公园散散步，顺便买些新鲜的水果回来。',
  'mid': '请把明天会议需要的材料整理好，九点之前发到我的邮箱，谢谢。',
  'near': '这是我的声音，只有我说的话才会被记录下来，其他人的声音会被过滤。'
};

type CloudSync = 'unknown' | 'checking' | 'synced' | 'missing' | 'unreachable';
type SessionPhase = 'idle' | 'connecting' | 'listening' | 'finishing';

class TranscriptLine {
  id: number;
  /** 'text' is a final sentence; 'divider' marks the start of a later recognition session. */
  kind: 'text' | 'divider';
  text: string;
  similarity: number;
  time: string;
  engine: EngineKind;
  /** Saved audio of this sentence (raw 16 kHz PCM16), '' when none was kept. */
  clipPath: string = '';

  constructor(id: number, text: string, similarity: number, engine: EngineKind,
    kind: 'text' | 'divider' = 'text') {
    this.id = id;
    this.kind = kind;
    this.text = text;
    this.similarity = similarity;
    this.engine = engine;
    const now = new Date();
    const pad = (value: number): string => (value < 10 ? `0${value}` : `${value}`);
    this.time = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  }
}

class PendingFinal {
  text: string;
  similarity: number;
  clip: Int16Array;

  constructor(text: string, similarity: number, clip: Int16Array) {
    this.text = text;
    this.similarity = similarity;
    this.clip = clip;
  }
}

class SessionEvents implements RecognizerEvents {
  private owner: Index;
  private token: number;

  constructor(owner: Index, token: number) {
    this.owner = owner;
    this.token = token;
  }

  onListening(): void {
    this.owner.onSessionListening(this.token);
  }

  onPartial(text: string, confirmed?: boolean): void {
    this.owner.onSessionPartial(this.token, text, confirmed ?? true);
  }

  onFinal(text: string, similarity?: number, startSample?: number, endSample?: number): void {
    this.owner.onSessionFinal(this.token, text, similarity, startSample, endSample);
  }

  onFiltered(): void {
    this.owner.onSessionFiltered(this.token);
  }

  onComplete(): void {
    this.owner.onSessionComplete(this.token);
  }

  onError(message: string): void {
    this.owner.onSessionError(this.token, message);
  }
}

/** versionName of the installed bundle, so the footer always matches AppScope/app.json5. */
function installedVersion(): string {
  try {
    return bundleManager.getBundleInfoForSelfSync(bundleManager.BundleFlag.GET_BUNDLE_INFO_DEFAULT).versionName;
  } catch (_e) {
    return '';
  }
}

@Entry
@Component
struct Index {
  // ---- engine & connectivity ----
  @State engine: EngineKind = 'local';
  @State localState: LocalState = 'idle';
  @State localMessage: string = '';
  @State cloudSync: CloudSync = 'unknown';
  @State language: RecognitionLanguage = 'zh';
  @State cloudBase: string = '';

  // ---- voiceprint ----
  @State profileName: string = '';
  @State localId: string = '';
  @State cloudId: string = '';
  @State samples: SampleInfo[] = [];
  @State recordingSlot: string = '';
  @State recordingSec: number = 0;
  @State playingSlot: string = '';
  @State registering: boolean = false;
  @State registerStep: string = '';
  // True after a sample is re-recorded, so the next registration replaces both sides.
  @State samplesDirty: boolean = false;
  @State enrollOpen: boolean = false;
  // All enrolled people; exactly one (the active profile) is the recognition target at a time.
  @State profiles: VoiceprintProfile[] = [];
  @State activeProfileId: string = '';
  @State addingProfile: boolean = false;
  @State newProfileName: string = '';

  // ---- recognition ----
  @State phase: SessionPhase = 'idle';
  @State lines: TranscriptLine[] = [];
  @State partial: string = '';
  // What the live row shows: recognizer output revealed steadily by SmoothText.
  @State liveText: string = '';
  private appVersion: string = installedVersion();
  // Leading characters of liveText that stopped changing: drawn in ink, the fresh tail stays light.
  @State liveSettled: number = 0;
  // Fades the live row out when another speaker's preview is withdrawn.
  @State liveOpacity: number = 1;
  @State sentencePlayback: boolean = true;
  @State strongFilter: boolean = true;
  @State playingLineId: number = -1;
  @State filteredCount: number = 0;
  @State elapsedSec: number = 0;
  @State levels: number[] = new Array<number>(LEVEL_BARS).fill(0);
  @State level: number = 0;
  @State breathe: boolean = false;

  @StorageProp('insetTopPx') insetTopPx: number = 0;
  @StorageProp('insetBottomPx') insetBottomPx: number = 0;

  // ---- sheet ----
  @State settingsOpen: boolean = false;
  @State draftBase: string = '';

  private context: common.UIAbilityContext = getContext(this) as common.UIAbilityContext;
  private store?: VoiceprintSamples;
  private localListener = (state: LocalState, message: string): void => {
    this.localState = state;
    this.localMessage = message;
    if (state === 'ready') this.autoSync();
  };
  private enrollRecorder?: AudioRecorder;
  private enrollChunks: Int16Array[] = [];
  private enrollSamples: number = 0;
  private enrollTimer: number = -1;
  private player: PcmPlayer = new PcmPlayer();

  private recognizer?: TargetRecognizer;
  private sessionToken: number = 0;
  private sessionRecorder?: AudioRecorder;
  private frameWriter?: PcmFrameWriter;
  private sessionEngine: EngineKind = 'local';
  private sessionStartedAt: number = 0;
  private clockTimer: number = -1;
  private levelTimer: number = -1;
  private pendingLevel: number = 0;
  private lineSeq: number = 0;
  private lastAutoSyncAt: number = 0;
  private smoother: SmoothText = new SmoothText();
  // Finals finish typing in the live row before they are committed, in arrival order.
  private finalQueue: PendingFinal[] = [];
  private smoothTimer: number = -1;
  private lastFollowAt: number = 0;
  private debug?: DebugSession;
  private stopReplay?: () => void;
  private replaying: boolean = false;
  // Per character of the current partial: since when that prefix has stayed unchanged (ms).
  private partialStableSince: number[] = [];
  // A run of another speaker's audio counts once, however many rejection windows it spans.
  private filteredOpen: boolean = false;
  private withdrawToken: number = 0;
  // A preview not yet attributed to the enrolled speaker stays light until it is.
  private partialConfirmed: boolean = true;

  private clips?: SentenceClips;
  // True while the reader is at the newest line; new text only auto-scrolls in that case.
  @State followTail: boolean = true;
  private scroller: Scroller = new Scroller();

  aboutToAppear(): void {
    this.engine = AppPrefs.engine(this.context);
    this.language = AppPrefs.language(this.context);
    this.cloudBase = AppPrefs.cloudBase(this.context);
    this.loadActiveProfile();
    LocalEngine.get().observe(this.localListener);
    LocalEngine.get().prepare(this.context);
    this.sentencePlayback = AppPrefs.sentencePlayback(this.context);
    this.strongFilter = AppPrefs.strongFilter(this.context);
    this.clips = new SentenceClips(this.context.filesDir);
    if (DebugSession.enabled()) {
      this.debug = new DebugSession(this.context.filesDir);
      this.watchReplayRequest();
    }
    this.requestMicrophone().then((granted: boolean): void => {
      if (!granted) this.toast('需要麦克风权限才能录制声纹和识别');
    });
    this.refreshCloudStatus();
  }

  aboutToDisappear(): void {
    LocalEngine.get().unobserve(this.localListener);
    this.cancelEnrollRecording();
    this.player.stop();
    this.abortSession();
  }

  // ======================================================================
  // Voiceprint
  // ======================================================================

  private reloadSamples(): void {
    this.samples = this.store?.all() ?? [];
  }

  private hasAnyVoiceprint(): boolean {
    return this.localId.length > 0 || this.cloudId.length > 0;
  }

  private samplesComplete(): boolean {
    return this.samples.length === SAMPLE_SLOTS.length &&
      this.samples.every((item: SampleInfo): boolean => item.valid);
  }

  private voiceprintSynced(): boolean {
    return this.localId.length > 0 && this.cloudId.length > 0 && this.cloudSync !== 'missing';
  }

  private async refreshCloudStatus(): Promise<void> {
    if (this.cloudId.length === 0) {
      this.cloudSync = 'unknown';
      this.autoSync();
      return;
    }
    this.cloudSync = 'checking';
    const status: CloudEnrollmentStatus =
      await new CloudVoiceprint(this.cloudBase, AppPrefs.profileKey(this.context)).status();
    if (status.available === true && status.enrollmentId.length > 0) {
      if (status.enrollmentId !== this.cloudId) {
        this.cloudId = status.enrollmentId;
        AppPrefs.setCloudEnrollmentId(this.context, this.cloudId);
      }
      this.cloudSync = 'synced';
    } else if (status.available === false) {
      this.cloudSync = 'missing';
    } else {
      this.cloudSync = 'unreachable';
    }
    this.autoSync();
  }

  private startEnrollRecording(slot: SampleSlot): void {
    if (this.recordingSlot.length > 0 || this.registering || this.phase !== 'idle') return;
    this.player.stop();
    this.playingSlot = '';
    this.enrollChunks = [];
    this.enrollSamples = 0;
    this.recordingSlot = slot;
    this.recordingSec = 0;
    this.levels = new Array<number>(LEVEL_BARS).fill(0);
    const recorder = new AudioRecorder(
      (pcm: Int16Array): void => {
        this.enrollChunks.push(pcm);
        this.enrollSamples += pcm.length;
        this.pendingLevel = Math.max(this.pendingLevel, Index.levelOf(pcm));
        this.recordingSec = this.enrollSamples / 16000;
        if (this.recordingSec >= SAMPLE_MAX_SEC) this.stopEnrollRecording();
      },
      (message: string): void => {
        hilog.warn(0x0000, 'AmphionVoice', 'enroll capture: %{public}s', message);
        this.toast('麦克风暂时不可用，请稍后重试');
        this.cancelEnrollRecording();
      });
    this.enrollRecorder = recorder;
    this.startLevelTicker();
    recorder.start();
  }

  private async stopEnrollRecording(): Promise<void> {
    const slot = this.recordingSlot as SampleSlot;
    const recorder = this.enrollRecorder;
    if (recorder === undefined || slot.length === 0) return;
    this.enrollRecorder = undefined;
    await recorder.stop();
    this.stopLevelTicker();
    const total = this.enrollChunks.reduce((sum: number, chunk: Int16Array): number => sum + chunk.length, 0);
    const pcm = new Int16Array(Math.min(total, SAMPLE_MAX_SEC * 16000));
    let offset = 0;
    for (let i = 0; i < this.enrollChunks.length && offset < pcm.length; i++) {
      const chunk = this.enrollChunks[i].subarray(0, pcm.length - offset);
      pcm.set(chunk, offset);
      offset += chunk.length;
    }
    this.enrollChunks = [];
    this.recordingSlot = '';
    if (pcm.length < SAMPLE_MIN_SEC * 16000) {
      this.toast(`录音不足 ${SAMPLE_MIN_SEC} 秒，请读完提示语`);
      return;
    }
    // 真机外放测试时三段录音只有约 -50 dBFS 的底噪也注册成功了；没有足够人声的录音不保存。
    if (voicedSeconds(pcm) < VOICED_MIN_SEC) {
      this.toast('没有录到清晰的说话声，请靠近麦克风朗读后重录');
      return;
    }
    this.store?.save(slot, pcm);
    this.samplesDirty = true;
    this.reloadSamples();
  }

  private cancelEnrollRecording(): void {
    const recorder = this.enrollRecorder;
    this.enrollRecorder = undefined;
    this.enrollChunks = [];
    this.recordingSlot = '';
    this.stopLevelTicker();
    recorder?.stop();
  }

  private togglePlay(slot: SampleSlot): void {
    if (this.playingSlot === slot) {
      this.player.stop();
      this.playingSlot = '';
      return;
    }
    const pcm = this.store?.read(slot);
    if (pcm === undefined || pcm.length === 0) return;
    this.playingSlot = slot;
    this.player.play(pcm, (): void => {
      if (this.playingSlot === slot) this.playingSlot = '';
    });
  }

  private localNeedsSync(): boolean {
    return this.localId.length === 0;
  }

  private cloudNeedsSync(): boolean {
    return this.cloudId.length === 0 || this.cloudSync === 'missing';
  }

  /**
   * One action keeps both engines on the same three recordings.
   * scope 'all' re-registers both sides (new recordings); 'missing' only fills the side that lacks one.
   * silent runs in the background without failure toasts. Resolves true when every attempted side succeeded.
   */
  private async registerVoiceprint(scope: 'all' | 'missing' = 'all', silent: boolean = false): Promise<boolean> {
    if (!this.samplesComplete() || this.registering) return false;
    const store = this.store;
    if (store === undefined) return false;
    const doLocal = scope === 'all' || this.localNeedsSync();
    const doCloud = scope === 'all' || this.cloudNeedsSync();
    if (!doLocal && !doCloud) return true;
    this.player.stop();
    this.playingSlot = '';
    this.registering = true;
    const paths: Record<string, string> = {};
    SAMPLE_SLOTS.forEach((slot: SampleSlot): void => {
      paths[slot] = store.pathOf(slot);
    });

    let localError = '';
    if (doLocal) {
      this.registerStep = '正在注册声纹';
      await Index.nextFrame();
      try {
        const id = LocalEngine.get().register(SAMPLE_SLOTS.map((slot: SampleSlot): string => paths[slot]), this.localId);
        this.localId = id;
        AppPrefs.setLocalVoiceprintId(this.context, id);
      } catch (e) {
        localError = (e as Error).message;
      }
    }

    let cloudError = '';
    if (doCloud) {
      this.registerStep = '正在注册声纹';
      const cloud = new CloudVoiceprint(this.cloudBase, AppPrefs.profileKey(this.context));
      try {
        const previous = this.cloudId;
        const id = await cloud.register(paths);
        this.cloudId = id;
        AppPrefs.setCloudEnrollmentId(this.context, id);
        this.cloudSync = 'synced';
        if (previous.length > 0 && previous !== id) cloud.remove(previous).catch((): void => {});
      } catch (e) {
        cloudError = (e as Error).message;
        if (this.cloudId.length > 0) this.cloudSync = 'missing';
      }
    }

    this.registering = false;
    this.registerStep = '';
    this.profiles = AppPrefs.profiles(this.context);
    const ok = localError.length === 0 && cloudError.length === 0;
    if (scope === 'all' && (!doLocal || localError.length === 0 || !doCloud || cloudError.length === 0)) {
      // At least one side now holds the new recordings. A side that failed is marked missing so the
      // button and the background sync complete it from the same recordings instead of asking to re-record.
      this.samplesDirty = false;
      if (doLocal && localError.length > 0 && this.localId.length > 0) {
        LocalEngine.get().remove(this.localId);
        this.localId = '';
        AppPrefs.setLocalVoiceprintId(this.context, '');
      }
      if (doCloud && cloudError.length > 0 && this.cloudId.length > 0) {
        // Status checks would report the old enrollment as usable, so drop it rather than mark it.
        const stale = this.cloudId;
        this.cloudId = '';
        AppPrefs.setCloudEnrollmentId(this.context, '');
        this.cloudSync = 'unknown';
        new CloudVoiceprint(this.cloudBase, AppPrefs.profileKey(this.context)).remove(stale).catch((): void => {});
      }
    }
    if (ok) {
      this.enrollOpen = false;
      if (!silent) this.toast('声纹注册完成');
    } else {
      // Both sides register from the same recordings; the user only ever sees one voiceprint.
      hilog.warn(0x0000, 'AmphionVoice', 'register local=%{public}s cloud=%{public}s', localError, cloudError);
      if (!silent) this.toast(`声纹注册未完成：${localError.length > 0 ? localError : cloudError}`);
    }
    return ok;
  }

  /** Quietly fills whichever side is missing a voiceprint, reusing the saved recordings. */
  private autoSync(): void {
    if (this.registering || this.phase !== 'idle' || this.recordingSlot.length > 0) return;
    if (!this.samplesComplete() || !this.hasAnyVoiceprint()) return;
    const local = this.localNeedsSync() && this.localState === 'ready';
    const cloud = this.cloudNeedsSync() && this.cloudSync !== 'checking';
    if (!local && !cloud) return;
    // Background retries are throttled; an explicit tap on 同步 or 开始 always goes through.
    const now = Date.now();
    if (now - this.lastAutoSyncAt < 60000) return;
    this.lastAutoSyncAt = now;
    this.registerVoiceprint('missing', true);
  }

  // ---- profiles ---------------------------------------------------------------------

  /** Loads the active profile's ids and recordings into the page state. */
  private loadActiveProfile(): void {
    this.profiles = AppPrefs.profiles(this.context);
    const active = AppPrefs.activeProfile(this.context);
    this.activeProfileId = active?.id ?? '';
    this.profileName = active?.name ?? '';
    this.localId = active?.localId ?? '';
    this.cloudId = active?.cloudId ?? '';
    this.store = new VoiceprintSamples(this.context.filesDir, this.activeProfileId);
    this.samplesDirty = false;
    this.cloudSync = 'unknown';
    this.reloadSamples();
  }

  private profileBusy(): boolean {
    return this.phase !== 'idle' || this.registering || this.recordingSlot.length > 0;
  }

  private switchProfile(id: string): void {
    if (id === this.activeProfileId) return;
    if (this.profileBusy()) {
      this.toast('请先结束当前录音或识别');
      return;
    }
    this.player.stop();
    this.playingSlot = '';
    AppPrefs.setActiveProfile(this.context, id);
    this.loadActiveProfile();
    this.refreshCloudStatus();
    this.toast(`现在识别：${this.profileName}`);
  }

  private confirmAddProfile(): void {
    const name = this.newProfileName.trim();
    if (name.length === 0) {
      this.toast('请输入名字');
      return;
    }
    if (this.profiles.some((p: VoiceprintProfile): boolean => p.name === name)) {
      this.toast('已有同名声纹');
      return;
    }
    if (this.profileBusy()) return;
    this.player.stop();
    this.playingSlot = '';
    AppPrefs.addProfile(this.context, name);
    this.addingProfile = false;
    this.newProfileName = '';
    this.loadActiveProfile();
  }

  private confirmDeleteProfile(profile: VoiceprintProfile): void {
    if (this.profileBusy()) {
      this.toast('请先结束当前录音或识别');
      return;
    }
    AlertDialog.show({
      title: `删除「${profile.name}」的声纹`,
      message: '将删除这个人的声纹及三段录音，之后不会再识别这个人。',
      autoCancel: true,
      alignment: DialogAlignment.Bottom,
      offset: { dx: 0, dy: -20 },
      primaryButton: { value: '取消', action: (): void => {} },
      secondaryButton: { value: '删除', fontColor: Palette.DANGER, action: (): void => { this.deleteProfile(profile); } }
    });
  }

  /** Removes both registrations of a profile, its recordings and the profile itself. */
  private async deleteProfile(profile: VoiceprintProfile): Promise<void> {
    this.player.stop();
    this.playingSlot = '';
    LocalEngine.get().remove(profile.localId);
    VoiceprintSamples.removeProfile(this.context.filesDir, profile.id);
    AppPrefs.removeProfile(this.context, profile.id);
    this.loadActiveProfile();
    this.refreshCloudStatus();
    this.toast(`已删除「${profile.name}」的声纹`);
    if (profile.cloudId.length === 0) return;
    try {
      await new CloudVoiceprint(this.cloudBase, profile.key).remove(profile.cloudId);
    } catch (e) {
      hilog.warn(0x0000, 'AmphionVoice', 'remote voiceprint delete: %{public}s', (e as Error).message);
    }
  }

  private profileStatus(p: VoiceprintProfile): string {
    if (p.id === this.activeProfileId) {
      if (this.registering) return '正在注册';
      if (this.voiceprintSynced()) return '已注册';
      return this.hasAnyVoiceprint() ? '注册未完成' : '待录制';
    }
    return p.localId.length > 0 && p.cloudId.length > 0 ? '已注册' : (p.localId.length > 0 || p.cloudId.length > 0 ? '注册未完成' : '待录制');
  }

  // ======================================================================
  // Recognition
  // ======================================================================

  private selectEngine(engine: EngineKind): void {
    if (this.phase !== 'idle' || this.engine === engine) return;
    animateTo({ duration: Motion.BASE, curve: Curve.FastOutSlowIn }, (): void => {
      this.engine = engine;
    });
    AppPrefs.setEngine(this.context, engine);
    if (engine === 'cloud') this.refreshCloudStatus();
  }

  private onMicTap(): void {
    if (this.phase === 'idle') {
      this.withMicrophone((): void => { this.syncThenStart(); });
    }
    else if (this.phase === 'listening' || this.phase === 'connecting') this.stopSession();
  }

  private async syncThenStart(): Promise<void> {
    const missing = this.engine === 'local' ? this.localNeedsSync() : this.cloudNeedsSync();
    if (missing && this.samplesComplete() && (this.engine === 'cloud' || this.localState === 'ready')) {
      if (!await this.registerVoiceprint('missing')) return;
    }
    this.startSession();
  }

  private startSession(replayFile: string = ''): void {
    if (this.recordingSlot.length > 0 || this.registering) return;
    const engine = this.engine;
    if (engine === 'local') {
      if (this.localId.length === 0) {
        this.promptEnroll('请先注册声纹');
        return;
      }
      if (this.localState !== 'ready') {
        this.toast(this.localState === 'failed' ? this.localMessage : '识别服务准备中，请稍候');
        return;
      }
      this.recognizer = new LocalRecognizer(this.localId, this.strongFilter);
    } else {
      if (this.cloudId.length === 0 || this.cloudSync === 'missing') {
        this.promptEnroll(this.localId.length > 0 ? '请重新录制声纹以完成注册' : '请先注册声纹');
        return;
      }
      this.recognizer = new CloudRecognizer(this.cloudBase, this.cloudId, this.language, this.strongFilter);
    }
    this.player.stop();
    this.playingSlot = '';
    this.sessionEngine = engine;
    this.sessionToken += 1;
    this.partial = '';
    this.elapsedSec = 0;
    if (this.lines.length > 0) {
      this.lineSeq += 1;
      this.lines = this.lines.concat([new TranscriptLine(this.lineSeq, '', -1, engine, 'divider')]);
    }
    this.phase = 'connecting';
    this.followTail = true;
    this.followLiveEdge();
    this.recognizer.start(new SessionEvents(this, this.sessionToken));
    this.resetLive();
    this.clips?.begin();
    this.debug?.begin();
    this.replaying = replayFile.length > 0;

    const writer = new PcmFrameWriter((frame: ArrayBuffer): void => this.recognizer?.write(frame));
    this.frameWriter = writer;
    const onPcm = (pcm: Int16Array): void => {
      this.pendingLevel = Math.max(this.pendingLevel, Index.levelOf(pcm));
      this.debug?.capture(pcm);
      this.clips?.append(pcm);
      writer.accept(pcm);
    };
    if (this.replaying) {
      this.sessionStartedAt = Date.now();
      this.levels = new Array<number>(LEVEL_BARS).fill(0);
      this.startLevelTicker();
      this.clockTimer = setInterval((): void => {
        this.elapsedSec = Math.floor((Date.now() - this.sessionStartedAt) / 1000);
      }, 500);
      this.stopReplay = DebugSession.replay(replayFile, onPcm, (): void => { this.stopSession(); });
      return;
    }
    const recorder = new AudioRecorder(
      onPcm,
      (message: string): void => {
        hilog.warn(0x0000, 'AmphionVoice', 'session capture: %{public}s', message);
        this.toast('麦克风暂时不可用，请稍后重试');
        this.abortSession();
      });
    this.sessionRecorder = recorder;
    this.sessionStartedAt = Date.now();
    this.levels = new Array<number>(LEVEL_BARS).fill(0);
    this.startLevelTicker();
    this.clockTimer = setInterval((): void => {
      this.elapsedSec = Math.floor((Date.now() - this.sessionStartedAt) / 1000);
    }, 500);
    recorder.start();
  }

  private async stopSession(): Promise<void> {
    if (this.phase !== 'listening' && this.phase !== 'connecting') return;
    this.phase = 'finishing';
    await this.stopCapture();
    this.recognizer?.finish();
  }

  private async stopCapture(): Promise<void> {
    this.stopReplay?.();
    this.stopReplay = undefined;
    const recorder = this.sessionRecorder;
    this.sessionRecorder = undefined;
    clearInterval(this.clockTimer);
    this.stopLevelTicker();
    if (recorder !== undefined) await recorder.stop();
    this.frameWriter?.flushFinalFrame();
    this.frameWriter = undefined;
  }

  private abortSession(): void {
    this.sessionToken += 1;
    this.recognizer?.cancel();
    this.recognizer = undefined;
    this.stopCapture();
    this.phase = 'idle';
    this.partial = '';
    this.flushLive();
  }

  onSessionListening(token: number): void {
    if (token !== this.sessionToken) return;
    if (this.phase === 'connecting') this.phase = 'listening';
  }

  onSessionPartial(token: number, rawText: string, confirmed: boolean = true): void {
    if (token !== this.sessionToken) return;
    this.partialConfirmed = confirmed;
    // Previews often end in a full stop that the next update drops; the final carries punctuation.
    const text = rawText.replace(/[。，,.？?！!、；;：:\s]+$/, '');
    const keep = SmoothText.commonPrefix(this.partial, text);
    const now = Date.now();
    this.partialStableSince = this.partialStableSince.slice(0, keep);
    for (let i = keep; i < text.length; i++) this.partialStableSince.push(now);
    this.partial = text;
    if (text.length > 0 && this.liveOpacity < 1) {
      // New speech while a withdrawal fades: drop the fading text and start the new line clean.
      this.withdrawToken++;
      this.smoother.reset('');
      this.liveText = '';
      this.liveSettled = 0;
      this.liveOpacity = 1;
    }
    if (text.length > 0) this.clips?.noteSpeech();
    this.debug?.mark(this.liveText, this.lines.length, `partial:${text}`);
    this.ensureSmoothing();
  }

  /** Keeps the newest line in view without animation, so updates never make the page bounce. */
  private followLiveEdge(): void {
    if (!this.followTail) return;
    setTimeout((): void => {
      if (this.followTail) this.scroller.scrollEdge(Edge.Bottom);
    }, 16);
  }

  // ---- steady live text ----------------------------------------------------------

  private resetLive(): void {
    this.finalQueue = [];
    this.partial = '';
    this.partialStableSince = [];
    this.filteredOpen = false;
    this.smoother.reset('');
    this.liveText = '';
    this.liveSettled = 0;
  }

  private ensureSmoothing(): void {
    if (this.smoothTimer >= 0) return;
    this.smoothTimer = setInterval((): void => this.smoothTick(), 33);
  }

  private smoothTick(): void {
    const isFinal = this.finalQueue.length > 0;
    // Partials are shown as soon as they arrive: first-character latency matters more than hiding a
    // brief preview that the final later corrects.
    this.smoother.setTarget(isFinal ? this.finalQueue[0].text : this.partial, isFinal,
      this.finalQueue.length > 1);
    if (this.smoother.tick()) {
      this.liveText = this.smoother.current();
      this.debug?.mark(this.liveText, this.lines.length);
      const now = Date.now();
      if (now - this.lastFollowAt > 120) {
        this.lastFollowAt = now;
        this.followLiveEdge();
      }
    }
    const settled = isFinal || this.partialConfirmed ? this.smoother.settledLength() : 0;
    if (settled !== this.liveSettled) this.liveSettled = settled;
    if (this.finalQueue.length > 0 && this.smoother.settled()) {
      this.commitFinal(this.finalQueue.shift() as PendingFinal);
    }
    if (this.finalQueue.length === 0 && this.smoother.settled() && this.phase === 'idle') {
      clearInterval(this.smoothTimer);
      this.smoothTimer = -1;
    }
  }

  /** The typed sentence moves into the transcript in the same frame the live row clears. */
  private commitFinal(final: PendingFinal): void {
    this.lineSeq += 1;
    const line = new TranscriptLine(this.lineSeq, final.text, final.similarity, this.sessionEngine);
    line.clipPath = this.clips?.save(line.id, final.clip) ?? '';
    this.lines = this.lines.concat([line]);
    this.smoother.reset('');
    this.liveText = '';
    this.liveSettled = 0;
    this.debug?.mark('', this.lines.length, 'commit');
    this.followLiveEdge();
  }

  /** Session over: anything still typing is committed at once rather than left half-shown. */
  private flushLive(): void {
    while (this.finalQueue.length > 0) this.commitFinal(this.finalQueue.shift() as PendingFinal);
    this.partial = '';
    this.smoother.reset('');
    this.liveText = '';
    this.liveSettled = 0;
    if (this.smoothTimer >= 0) {
      clearInterval(this.smoothTimer);
      this.smoothTimer = -1;
    }
  }

  private jumpToLatest(): void {
    this.followTail = true;
    this.scroller.scrollEdge(Edge.Bottom);
  }

  onSessionFinal(token: number, text: string, similarity?: number, startSample?: number,
    endSample?: number): void {
    if (token !== this.sessionToken) return;
    // The final supersedes this sentence's partials; the next partial belongs to the next sentence.
    const clip = this.clips?.take(startSample, endSample) ?? new Int16Array(0);
    this.finalQueue.push(new PendingFinal(text, similarity ?? -1, clip));
    this.partial = '';
    this.partialStableSince = [];
    this.filteredOpen = false;
    this.debug?.mark(this.liveText, this.lines.length, `final:${text}`);
    this.ensureSmoothing();
  }

  onSessionFiltered(token: number): void {
    if (token !== this.sessionToken) return;
    if (!this.filteredOpen) {
      this.filteredCount += 1;
      this.filteredOpen = true;
    }
    this.partial = '';
    this.partialStableSince = [];
    this.clips?.discardCurrent();
    this.debug?.mark(this.liveText, this.lines.length, 'filtered');
    if (this.finalQueue.length === 0 && this.liveText.length > 0) {
      // Another speaker's preview fades out rather than vanishing or being typed backwards.
      const token = ++this.withdrawToken;
      animateTo({ duration: Motion.FAST, curve: Curve.EaseOut, onFinish: (): void => {
        if (token !== this.withdrawToken) return;
        this.smoother.reset('');
        this.liveText = '';
        this.liveSettled = 0;
        this.liveOpacity = 1;
      } }, (): void => {
        this.liveOpacity = 0;
      });
    }
  }

  onSessionComplete(token: number): void {
    if (token !== this.sessionToken) return;
    this.recognizer = undefined;
    this.flushLive();
    this.stopCapture();
    this.phase = 'idle';
    this.debug?.mark('', this.lines.length, 'complete');
    this.debug?.end(!this.replaying, this.sessionEngine);
  }

  onSessionError(token: number, message: string): void {
    if (token !== this.sessionToken) return;
    this.recognizer = undefined;
    this.flushLive();
    this.stopCapture();
    this.phase = 'idle';
    this.debug?.mark('', this.lines.length, `error:${message}`);
    this.debug?.end(!this.replaying, this.sessionEngine);
    this.toast(message);
  }

  /**
   * Debug builds only: `aa start ... --ps replay <wav> [--ps engine local|cloud]` replays a file through
   * the normal session once the chosen engine is ready.
   */
  private watchReplayRequest(): void {
    const timer = setInterval((): void => {
      const file = AppStorage.get<string>('debugReplay') ?? '';
      if (file.length === 0 || this.phase !== 'idle') return;
      const engine = (AppStorage.get<string>('debugReplayEngine') ?? '') === 'cloud' ? 'cloud' : 'local';
      if (this.engine !== engine) this.selectEngine(engine);
      const ready = engine === 'local' ? (this.localState === 'ready' && this.localId.length > 0) :
        (this.cloudId.length > 0 && this.cloudSync !== 'checking');
      if (!ready) return;
      AppStorage.setOrCreate<string>('debugReplay', '');
      this.startSession(file);
    }, 500);
    if (timer < 0) clearInterval(timer);
  }

  private togglePlayLine(line: TranscriptLine): void {
    if (this.playingLineId === line.id) {
      this.player.stop();
      this.playingLineId = -1;
      return;
    }
    if (this.phase !== 'idle') return;
    const pcm = SentenceClips.read(line.clipPath);
    if (pcm.length === 0) {
      this.toast('这句没有可播放的音频');
      return;
    }
    this.player.stop();
    this.playingSlot = '';
    this.playingLineId = line.id;
    this.player.play(pcm, (): void => {
      if (this.playingLineId === line.id) this.playingLineId = -1;
    });
  }

  private clearTranscript(): void {
    this.player.stop();
    this.playingLineId = -1;
    this.clips?.clearAll();
    this.lines = [];
    this.filteredCount = 0;
    this.followTail = true;
  }

  // ======================================================================
  // Helpers
  // ======================================================================

  private startLevelTicker(): void {
    this.stopLevelTicker();
    this.levelTimer = setInterval((): void => {
      const value = this.pendingLevel;
      this.pendingLevel = 0;
      this.level = value;
      const next = this.levels.slice(1);
      next.push(value);
      this.levels = next;
    }, LEVEL_TICK_MS);
  }

  private stopLevelTicker(): void {
    clearInterval(this.levelTimer);
    this.levelTimer = -1;
    this.level = 0;
    this.pendingLevel = 0;
  }

  /** Maps chunk RMS to 0..1 over a -55..-12 dBFS window, which spans whisper to raised voice. */
  private static levelOf(pcm: Int16Array): number {
    if (pcm.length === 0) return 0;
    let sum = 0;
    for (let i = 0; i < pcm.length; i += 2) sum += pcm[i] * pcm[i];
    const rms = Math.sqrt(sum / Math.ceil(pcm.length / 2)) / 32768;
    const db = 20 * Math.log10(Math.max(rms, 1e-6));
    return Math.max(0, Math.min(1, (db + 55) / 43));
  }

  private static nextFrame(): Promise<void> {
    return new Promise<void>((resolve: () => void): void => {
      setTimeout(resolve, 60);
    });
  }

  private promptEnroll(message: string): void {
    this.toast(message);
    this.openEnroll();
  }

  private openEnroll(): void {
    if (this.profiles.length === 0 && this.phase === 'idle') {
      AppPrefs.addProfile(this.context, '我');
      this.loadActiveProfile();
    }
    if (this.phase !== 'idle') return;
    this.reloadSamples();
    this.enrollOpen = true;
  }

  private closeEnroll(): void {
    if (this.recordingSlot.length > 0) this.cancelEnrollRecording();
    this.player.stop();
    this.playingSlot = '';
  }

  /** Runs action once microphone access is granted; otherwise asks, then points to system settings. */
  private async withMicrophone(action: () => void): Promise<void> {
    const atManager = abilityAccessCtrl.createAtManager();
    const permission: Permissions = 'ohos.permission.MICROPHONE';
    try {
      const tokenId = this.context.applicationInfo.accessTokenId;
      if (atManager.checkAccessTokenSync(tokenId, permission) ===
        abilityAccessCtrl.GrantStatus.PERMISSION_GRANTED) {
        action();
        return;
      }
      if (await this.requestMicrophone()) {
        action();
        return;
      }
      const states = await atManager.requestPermissionOnSetting(this.context, [permission]);
      if (states.length > 0 && states[0] === abilityAccessCtrl.GrantStatus.PERMISSION_GRANTED) action();
      else this.toast('需要麦克风权限才能录音');
    } catch (_e) {
      this.toast('需要麦克风权限才能录音');
    }
  }

  private async requestMicrophone(): Promise<boolean> {
    const permissions: Permissions[] = ['ohos.permission.MICROPHONE'];
    try {
      const result = await abilityAccessCtrl.createAtManager().requestPermissionsFromUser(this.context, permissions);
      return result.authResults.length > 0 && result.authResults[0] === 0;
    } catch (_e) {
      return false;
    }
  }

  private toast(message: string): void {
    promptAction.showToast({ message: message, duration: 2200, bottom: 160 });
  }

  private formatClock(sec: number): string {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
  }

  // Status wording is identical for both engines: the page never tells which one is in use.
  private engineStatusText(): string {
    if (this.engine === 'local') {
      if (this.localState === 'ready') return this.localId.length > 0 ? '准备就绪' : '准备就绪 · 待注册声纹';
      if (this.localState === 'failed') return this.localMessage;
      return '正在准备';
    }
    if (this.cloudSync === 'checking') return '正在准备';
    if (this.cloudSync === 'unreachable') return '识别服务暂不可用';
    if (this.cloudId.length === 0 || this.cloudSync === 'missing') return '准备就绪 · 待注册声纹';
    return '准备就绪';
  }

  private engineStatusColor(): string {
    if (this.engine === 'local') {
      if (this.localState === 'ready') return Palette.OK;
      if (this.localState === 'failed') return Palette.LIVE;
      return Palette.ON_NIGHT_2;
    }
    if (this.cloudSync === 'synced') return Palette.OK;
    if (this.cloudSync === 'unreachable' || this.cloudSync === 'missing') return Palette.LIVE;
    return Palette.ON_NIGHT_2;
  }

  private dockHint(): string {
    if (this.phase === 'connecting') return '正在启动识别…';
    if (this.phase === 'listening') return '正在聆听 · 只记录你的声音';
    if (this.phase === 'finishing') return '正在整理最后一句…';
    return '轻点开始识别';
  }

  // ======================================================================
  // UI
  // ======================================================================

  build() {
    Stack({ alignContent: Alignment.Bottom }) {
      Column() {
        this.Header()
        this.Conversation()
      }
      .width('100%')
      .height('100%')

      this.Dock()
    }
    .width('100%')
    .height('100%')
    .backgroundColor(Palette.PAPER)
    .bindSheet($$this.settingsOpen, this.SettingsSheet(), {
      height: SheetSize.FIT_CONTENT,
      dragBar: true,
      backgroundColor: Palette.SURFACE,
      showClose: false
    })
  }

  // ---- header ----------------------------------------------------------------

  @Builder
  Header() {
    Column({ space: 14 }) {
      Row({ space: 8 }) {
        Row({ space: 10 }) {
          Image($r('app.media.app_icon')).width(26).height(26).borderRadius(7)
          Text('AMPHION')
            .fontSize(14)
            .fontWeight(FontWeight.Bold)
            .letterSpacing(4)
            .fontColor(Palette.ON_NIGHT)
        }
        Blank()
        this.VoiceprintChip()
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          Image($r('app.media.ic_more')).width(18).height(18).fillColor(Palette.ON_NIGHT_2)
        }
        .width(32)
        .height(32)
        .backgroundColor(Color.Transparent)
        .accessibilityText('更多')
        .bindMenu(this.MoreMenu())
      }
      .width('100%')

      Row({ space: 8 }) {
        Circle().width(6).height(6).fill(this.engineStatusColor())
        Text(this.engineStatusText()).fontSize(12).fontColor(Palette.ON_NIGHT_2)
      }
      .alignSelf(ItemAlign.Start)
    }
    .width('100%')
    .padding({ left: Space.GUTTER, right: Space.GUTTER, top: px2vp(this.insetTopPx) + 10, bottom: 18 })
    .linearGradient({ angle: 165, colors: [[Palette.NIGHT_2, 0], [Palette.NIGHT, 1]] })
    .background(this.HeroRings(), { align: Alignment.BottomEnd })
    .borderRadius({ bottomLeft: 28, bottomRight: 28 })
    .clip(true)
    .bindSheet($$this.enrollOpen, this.EnrollSheet(), {
      height: SheetSize.LARGE,
      dragBar: true,
      backgroundColor: Palette.SURFACE,
      showClose: false,
      onDisappear: (): void => this.closeEnroll()
    })
  }

  /** The only voiceprint affordance on the main screen: status at a glance, tap to manage. */
  @Builder
  VoiceprintChip() {
    Row({ space: 6 }) {
      if (!this.hasAnyVoiceprint()) {
        Image($r('app.media.ic_shield')).width(14).height(14).fillColor(Color.White)
        Text('注册声纹').fontSize(12).fontWeight(FontWeight.Medium).fontColor(Color.White)
      } else {
        if (this.registering) {
          LoadingProgress().width(14).height(14).color(Palette.ON_NIGHT)
        } else {
          Circle().width(6).height(6).fill(this.voiceprintSynced() ? Palette.OK : Palette.LIVE)
        }
        Text(this.registering ? '声纹注册中' : (this.voiceprintSynced() ? this.profileName : `${this.profileName} · 待完成`))
          .maxLines(1)
          .textOverflow({ overflow: TextOverflow.Ellipsis })
          .constraintSize({ maxWidth: 120 })
          .fontSize(12).fontWeight(FontWeight.Medium).fontColor(Palette.ON_NIGHT)
      }
    }
    .height(32)
    .padding({ left: 12, right: 12 })
    .borderRadius(Space.RADIUS_CHIP)
    .backgroundColor(this.hasAnyVoiceprint() ? '#1AFFFFFF' : Palette.BRAND)
    .opacity(this.phase === 'idle' ? 1 : 0.5)
    .accessibilityText('声纹管理')
    .onClick((): void => this.openEnroll())
  }

  @Builder
  HeroRings() {
    Stack() {
      Circle().width(150).height(150).fillOpacity(0).stroke(Palette.BRAND).strokeOpacity(0.16).strokeWidth(1.5)
      Circle().width(104).height(104).fillOpacity(0).stroke(Palette.BRAND_GLOW).strokeOpacity(0.22).strokeWidth(1.5)
      Circle().width(60).height(60).fillOpacity(0).stroke(Palette.BRAND_GLOW).strokeOpacity(0.32).strokeWidth(1.5)
    }
    .width(150)
    .height(150)
    // Drawn as the header background so it never sets the header height.
    .margin({ bottom: -64, right: -36 })
    .hitTestBehavior(HitTestMode.Transparent)
  }

  /**
   * The engine choice lives in this low-key overflow menu, not on the page. Labels stay neutral
   * so the page never reveals whether recognition runs on the device or on the server.
   */
  @Builder
  MoreMenu() {
    Menu() {
      MenuItemGroup({ header: '识别模式' }) {
        this.ModeItem('local', '标准')
        this.ModeItem('cloud', '增强')
      }
      MenuItem({ startIcon: $r('app.media.ic_tune'), content: '设置' })
        .onClick((): void => {
          this.draftBase = this.cloudBase;
          this.settingsOpen = true;
        })
    }
  }

  @Builder
  ModeItem(kind: EngineKind, label: string) {
    MenuItem({ content: label })
      .selected(this.engine === kind)
      .selectIcon(true)
      .enabled(this.phase === 'idle')
      .onClick((): void => this.selectEngine(kind))
  }

  // ---- voiceprint sheet ----------------------------------------------------

  @Builder
  EnrollSheet() {
    Scroll() {
      Column({ space: 0 }) {
        Row({ space: 12 }) {
          Stack() {
            Circle().width(44).height(44).fill(this.voiceprintSynced() ? Palette.OK_SOFT : Palette.BRAND_SOFT)
            Image($r('app.media.ic_shield')).width(22).height(22)
              .fillColor(this.voiceprintSynced() ? Palette.OK : Palette.BRAND)
          }
          Column({ space: 3 }) {
            Text('声纹').fontSize(19).fontWeight(FontWeight.Bold).fontColor(Palette.INK)
            Text('选择要识别的人').fontSize(12).fontColor(Palette.INK_3)
          }
          .alignItems(HorizontalAlign.Start)
          .layoutWeight(1)
          Button({ type: ButtonType.Circle }) {
            Image($r('app.media.ic_close')).width(18).height(18).fillColor(Palette.INK_2)
          }
          .width(36).height(36).backgroundColor(Palette.SURFACE_SUNK)
          .accessibilityText('关闭')
          .onClick((): void => { this.enrollOpen = false; })
        }
        .width('100%')

        this.ProfileList()

        Row({ space: 8 }) {
          Text(`${this.profileName}的录音`).fontSize(15).fontWeight(FontWeight.Medium).fontColor(Palette.INK)
          Text(this.voiceprintStatusText()).fontSize(12).fontColor(Palette.INK_3).layoutWeight(1)
            .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis })
        }
        .width('100%')
        .margin({ top: 24 })

        Column({ space: 10 }) {
          ForEach(this.samples, (item: SampleInfo) => {
            this.SampleRow(item)
          }, (item: SampleInfo) => `${this.activeProfileId}-${item.slot}-${item.present}-${item.valid}-${item.durationSec}`)
        }
        .width('100%')
        .margin({ top: 12 })

        if (this.recordingSlot.length > 0) {
          this.ReadingPrompt()
        }

        Button({ type: ButtonType.Capsule, stateEffect: true }) {
          Row({ space: 8 }) {
            if (this.registering) {
              LoadingProgress().width(20).height(20).color(Color.White)
            } else {
              Image($r('app.media.ic_sync')).width(18).height(18).fillColor(Color.White)
            }
            Text(this.registering ? this.registerStep : this.registerButtonText())
              .fontSize(16)
              .fontWeight(FontWeight.Medium)
              .fontColor(Color.White)
          }
        }
        .width('100%')
        .height(50)
        .margin({ top: 20 })
        .backgroundColor(this.samplesComplete() && this.recordingSlot.length === 0 ? Palette.INK : '#C9C6BE')
        .enabled(this.samplesComplete() && !this.registering && this.recordingSlot.length === 0 &&
          this.phase === 'idle')
        .onClick((): void => {
          this.registerVoiceprint(this.onlyCompletionPending() ? 'missing' : 'all');
        })

        Text(this.samplesComplete() ? '三段录音已就绪' :
          `依次录制三段，每段 ${SAMPLE_MIN_SEC}–${SAMPLE_MAX_SEC} 秒，读出提示语即可`)
          .fontSize(12)
          .fontColor(Palette.INK_3)
          .margin({ top: 10 })
          .alignSelf(ItemAlign.Center)

      }
      .width('100%')
      .padding({ left: 24, right: 24, top: 16, bottom: 32 })
    }
    .width('100%')
    .scrollBar(BarState.Off)
    .align(Alignment.Top)
  }

  @Builder
  ProfileList() {
    Column({ space: 8 }) {
      ForEach(this.profiles, (p: VoiceprintProfile) => {
        this.ProfileRow(p)
      }, (p: VoiceprintProfile) => `${p.id}-${p.name}-${p.localId}-${p.cloudId}-${this.activeProfileId}`)

      if (this.addingProfile) {
        Row({ space: 8 }) {
          TextInput({ text: this.newProfileName, placeholder: '名字，例如：张三' })
            .layoutWeight(1)
            .height(44)
            .fontSize(15)
            .maxLength(12)
            .borderRadius(12)
            .backgroundColor(Palette.SURFACE_SUNK)
            .defaultFocus(true)
            .onChange((value: string): void => { this.newProfileName = value; })
            .onSubmit((): void => this.confirmAddProfile())
          Text('取消').fontSize(14).fontColor(Palette.INK_3).padding(8)
            .onClick((): void => {
              this.addingProfile = false;
              this.newProfileName = '';
            })
          Button('添加', { type: ButtonType.Capsule })
            .height(36)
            .fontSize(14)
            .backgroundColor(Palette.INK)
            .onClick((): void => this.confirmAddProfile())
        }
        .width('100%')
      } else {
        Row({ space: 6 }) {
          Text('+').fontSize(18).fontColor(Palette.BRAND)
          Text('添加声纹').fontSize(15).fontWeight(FontWeight.Medium).fontColor(Palette.BRAND)
        }
        .height(44)
        .padding({ left: 14, right: 14 })
        .borderRadius(12)
        .border({ width: 1, color: Palette.LINE, style: BorderStyle.Dashed })
        .width('100%')
        .justifyContent(FlexAlign.Center)
        .opacity(this.profileBusy() ? 0.4 : 1)
        .onClick((): void => {
          if (this.profileBusy()) return;
          this.addingProfile = true;
        })
      }
    }
    .width('100%')
    .margin({ top: 18 })
  }

  @Builder
  ProfileRow(p: VoiceprintProfile) {
    Row({ space: 12 }) {
      Stack() {
        Circle().width(20).height(20).fill(Color.Transparent)
          .stroke(p.id === this.activeProfileId ? Palette.BRAND : Palette.INK_3).strokeWidth(2)
        if (p.id === this.activeProfileId) {
          Circle().width(10).height(10).fill(Palette.BRAND)
        }
      }
      Column({ space: 2 }) {
        Text(p.name).fontSize(16).fontWeight(FontWeight.Medium).fontColor(Palette.INK)
          .maxLines(1).textOverflow({ overflow: TextOverflow.Ellipsis })
        Text(p.id === this.activeProfileId ? `${this.profileStatus(p)} · 当前识别` : this.profileStatus(p))
          .fontSize(12)
          .fontColor(p.id === this.activeProfileId ? Palette.BRAND : Palette.INK_3)
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        Image($r('app.media.ic_close')).width(14).height(14).fillColor(Palette.INK_3)
      }
      .width(32)
      .height(32)
      .backgroundColor(Palette.SURFACE_SUNK)
      .accessibilityText(`删除${p.name}的声纹`)
      .onClick((): void => this.confirmDeleteProfile(p))
    }
    .width('100%')
    .padding({ left: 14, right: 10, top: 10, bottom: 10 })
    .borderRadius(14)
    .backgroundColor(p.id === this.activeProfileId ? Palette.BRAND_SOFT : Palette.SURFACE)
    .border({ width: 1, color: p.id === this.activeProfileId ? '#D6D7FB' : Palette.LINE })
    .onClick((): void => this.switchProfile(p.id))
  }

  /** True when the recordings are unchanged and only one side still lacks the voiceprint. */
  private onlyCompletionPending(): boolean {
    return !this.samplesDirty && this.hasAnyVoiceprint() && (this.localNeedsSync() || this.cloudNeedsSync());
  }

  private registerButtonText(): string {
    if (!this.hasAnyVoiceprint()) return '注册声纹';
    if (this.samplesDirty) return '用新录音更新声纹';
    if (this.onlyCompletionPending()) return '完成声纹注册';
    return '重新注册声纹';
  }

  private voiceprintStatusText(): string {
    if (this.registering) return '正在注册';
    if (!this.hasAnyVoiceprint()) return '录三段语音即可完成注册';
    if (this.voiceprintSynced()) return '已注册';
    return this.samplesComplete() ? '注册未完成，请点下方按钮完成' : '注册未完成，请重新录制三段语音';
  }

  @Builder
  SampleRow(item: SampleInfo) {
    Row({ space: 12 }) {
      Stack() {
        Circle().width(34).height(34)
          .fill(this.recordingSlot === item.slot ? Palette.LIVE : (item.valid ? Palette.INK : Palette.SURFACE_SUNK))
        if (item.valid && this.recordingSlot !== item.slot) {
          Image($r('app.media.ic_check')).width(16).height(16).fillColor(Color.White)
        } else {
          Text(`${SAMPLE_SLOTS.indexOf(item.slot) + 1}`)
            .fontSize(14)
            .fontWeight(FontWeight.Bold)
            .fontColor(this.recordingSlot === item.slot ? Color.White : Palette.INK_2)
        }
      }

      Column({ space: 3 }) {
        Text(slotLabel(item.slot)).fontSize(15).fontWeight(FontWeight.Medium).fontColor(Palette.INK)
        if (this.recordingSlot === item.slot) {
          Row({ space: 8 }) {
            LevelBars({ levels: this.levels.slice(LEVEL_BARS - 16), color: Palette.LIVE, barHeight: 16 })
            Text(`${this.recordingSec.toFixed(1)} / ${SAMPLE_MAX_SEC} 秒`)
              .fontSize(12)
              .fontColor(Palette.LIVE)
              .fontFeature('"tnum" on')
          }
        } else {
          Text(item.valid ? `已录制 ${item.durationSec.toFixed(1)} 秒` :
            (item.present && !item.voiced ? '没有录到清晰的说话声，请重录' : slotHint(item.slot)))
            .fontSize(12)
            .fontColor(item.present && !item.voiced ? Palette.LIVE : Palette.INK_3)
        }
      }
      .alignItems(HorizontalAlign.Start)
      .layoutWeight(1)

      if (item.valid && this.recordingSlot !== item.slot) {
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          Image(this.playingSlot === item.slot ? $r('app.media.ic_stop') : $r('app.media.ic_play'))
            .width(16).height(16).fillColor(Palette.INK)
        }
        .width(36)
        .height(36)
        .backgroundColor(Palette.SURFACE_SUNK)
        .accessibilityText(`试听${slotLabel(item.slot)}`)
        .onClick((): void => this.togglePlay(item.slot))
      }

      Button(this.recordingSlot === item.slot ? '完成' : (item.valid ? '重录' : '录制'),
        { type: ButtonType.Capsule, stateEffect: true })
        .fontSize(13)
        .fontWeight(FontWeight.Medium)
        .height(34)
        .padding({ left: 14, right: 14 })
        .fontColor(this.recordingSlot === item.slot ? Color.White : (item.valid ? Palette.INK : Color.White))
        .backgroundColor(this.recordingSlot === item.slot ? Palette.LIVE :
          (item.valid ? Palette.SURFACE_SUNK : Palette.BRAND))
        .enabled(!this.registering && this.phase === 'idle' &&
          (this.recordingSlot.length === 0 || this.recordingSlot === item.slot))
        .opacity(this.recordingSlot.length > 0 && this.recordingSlot !== item.slot ? 0.4 : 1)
        .onClick((): void => {
          if (this.recordingSlot === item.slot) this.stopEnrollRecording();
          else this.withMicrophone((): void => this.startEnrollRecording(item.slot));
        })
    }
    .width('100%')
    .padding({ left: 12, right: 12, top: 10, bottom: 10 })
    .borderRadius(16)
    .backgroundColor(this.recordingSlot === item.slot ? Palette.LIVE_SOFT : Color.Transparent)
    .border({ width: 1, color: this.recordingSlot === item.slot ? '#F6C9AE' : Palette.LINE })
  }

  @Builder
  ReadingPrompt() {
    Column({ space: 8 }) {
      Text('请用平常的语气朗读').fontSize(12).fontColor(Palette.INK_3)
      Text(SLOT_PROMPTS[this.recordingSlot] ?? '')
        .fontSize(18)
        .lineHeight(28)
        .fontWeight(FontWeight.Medium)
        .fontColor(Palette.INK)
      Progress({ value: this.recordingSec, total: SAMPLE_MAX_SEC, type: ProgressType.Linear })
        .color(this.recordingSec >= SAMPLE_MIN_SEC ? Palette.OK : Palette.LIVE)
        .backgroundColor(Palette.SURFACE_SUNK)
        .style({ strokeWidth: 4 })
        .width('100%')
        .margin({ top: 4 })
      Text(this.recordingSec >= SAMPLE_MIN_SEC ? '时长已足够，可以点「完成」' :
        `至少 ${SAMPLE_MIN_SEC} 秒，满 ${SAMPLE_MAX_SEC} 秒自动结束`)
        .fontSize(12)
        .fontColor(this.recordingSec >= SAMPLE_MIN_SEC ? Palette.OK : Palette.INK_3)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding(16)
    .margin({ top: 12 })
    .borderRadius(18)
    .backgroundColor(Palette.PAPER)
    .transition(TransitionEffect.OPACITY)
  }

  // ---- conversation ------------------------------------------------------------

  private hasTranscript(): boolean {
    return this.lines.length > 0 || this.phase !== 'idle';
  }

  private sentenceCount(): number {
    return this.lines.filter((line: TranscriptLine): boolean => line.kind === 'text').length;
  }

  @Builder
  Conversation() {
    Column() {
      // Fixed toolbar: always the same height, so nothing below it shifts when counts change.
      Row({ space: 10 }) {
        Text('转写').fontSize(13).fontWeight(FontWeight.Medium).fontColor(Palette.INK_2)
        if (this.sentenceCount() > 0) {
          Text(`${this.sentenceCount()} 句`).fontSize(12).fontColor(Palette.INK_3).fontFeature('"tnum" on')
        }
        Blank()
        if (this.lines.length > 0 && this.phase === 'idle') {
          Text('清空').fontSize(13).fontColor(Palette.INK_3).padding({ left: 8, top: 6, bottom: 6 })
            .onClick((): void => this.clearTranscript())
        }
      }
      .width('100%')
      .height(44)
      .padding({ left: Space.GUTTER, right: Space.GUTTER })
      .visibility(this.hasTranscript() ? Visibility.Visible : Visibility.Hidden)

      Stack({ alignContent: Alignment.Top }) {
        if (!this.hasTranscript()) {
          this.EmptyState()
        } else {
          List({ scroller: this.scroller }) {
            ForEach(this.lines, (line: TranscriptLine, index: number) => {
              ListItem() {
                if (line.kind === 'divider') {
                  this.DividerItem(line)
                } else {
                  this.LineItem(line, this.showsTime(index))
                }
              }
            }, (line: TranscriptLine) => `${line.id}`)
            if (this.phase !== 'idle' || this.liveText.length > 0) {
              ListItem() {
                this.LiveItem()
              }
            }
          }
          .width('100%')
          .height('100%')
          .padding({ left: Space.GUTTER, right: Space.GUTTER })
          .contentStartOffset(6)
          .contentEndOffset(200 + px2vp(this.insetBottomPx))
          .scrollBar(BarState.Off)
          .edgeEffect(EdgeEffect.None)
          .onScrollStop((): void => {
            this.followTail = this.scroller.isAtEnd();
          })
          .onReachEnd((): void => {
            this.followTail = true;
          })
        }

        // Soft edge under the toolbar instead of text being cut off hard.
        Column()
          .width('100%')
          .height(18)
          .linearGradient({ angle: 180, colors: [[Palette.PAPER, 0], ['#00F5F4F0', 1]] })
          .hitTestBehavior(HitTestMode.Transparent)

        if (!this.followTail && this.hasTranscript()) {
          Row({ space: 6 }) {
            Text('↓').fontSize(13).fontColor(Color.White)
            Text('回到最新').fontSize(13).fontWeight(FontWeight.Medium).fontColor(Color.White)
          }
          .height(34)
          .padding({ left: 14, right: 16 })
          .borderRadius(Space.RADIUS_CHIP)
          .backgroundColor(Palette.INK)
          .shadow({ radius: 12, color: '#33000000', offsetY: 4 })
          .position({ x: '50%', y: '100%' })
          .markAnchor({ x: 62, y: 250 + px2vp(this.insetBottomPx) })
          .onClick((): void => this.jumpToLatest())
        }
      }
      .layoutWeight(1)
      .width('100%')
      .clip(true)
    }
    .layoutWeight(1)
    .width('100%')
  }

  @Builder
  EmptyState() {
    Column({ space: 12 }) {
      if (!this.hasAnyVoiceprint()) {
        Text('只听见你').fontSize(30).fontWeight(FontWeight.Bolder).fontColor(Palette.INK)
        Text('注册一次声纹，只转写你本人的声音，身边的交谈自动过滤。')
          .fontSize(14).lineHeight(22).fontColor(Palette.INK_2).textAlign(TextAlign.Center)
        Button('注册声纹', { type: ButtonType.Capsule, stateEffect: true })
          .height(44)
          .padding({ left: 28, right: 28 })
          .fontSize(15)
          .fontWeight(FontWeight.Medium)
          .backgroundColor(Palette.INK)
          .margin({ top: 8 })
          .onClick((): void => this.openEnroll())
        Text('约 30 秒 · 录三段语音').fontSize(12).fontColor(Palette.INK_3)
      } else {
        Stack() {
          Circle().width(64).height(64).fill(Palette.BRAND_SOFT)
          Image($r('app.media.ic_wave')).width(28).height(28).fillColor(Palette.BRAND)
        }
        Text('轻点下方按钮开始说话').fontSize(16).fontWeight(FontWeight.Medium).fontColor(Palette.INK)
        Text('说话内容会实时出现在这里，\n旁人的声音会被自动过滤。')
          .fontSize(13).lineHeight(20).fontColor(Palette.INK_3).textAlign(TextAlign.Center)
      }
    }
    .width('100%')
    .padding({ left: 32, right: 32, top: this.hasAnyVoiceprint() ? 72 : 48 })
  }

  /** Time is shown once per minute (and after a divider), not repeated on every sentence. */
  private showsTime(index: number): boolean {
    if (index === 0) return true;
    const previous = this.lines[index - 1];
    return previous.kind === 'divider' || previous.time !== this.lines[index].time;
  }

  /** A committed sentence: time in a fixed gutter, text in ink. Same metrics as LiveItem. */
  @Builder
  LineItem(line: TranscriptLine, showTime: boolean) {
    Row({ space: 14 }) {
      Text(showTime ? line.time : '')
        .width(40)
        .fontSize(12)
        .lineHeight(29)
        .fontColor(Palette.INK_3)
        .fontFeature('"tnum" on')
      Text(line.text)
        .layoutWeight(1)
        .fontSize(18)
        .lineHeight(29)
        .fontColor(Palette.INK)
        .copyOption(CopyOptions.LocalDevice)
      if (this.sentencePlayback && line.clipPath.length > 0) {
        Button({ type: ButtonType.Circle, stateEffect: true }) {
          Image(this.playingLineId === line.id ? $r('app.media.ic_stop') : $r('app.media.ic_play'))
            .width(12).height(12)
            .fillColor(this.playingLineId === line.id ? Palette.LIVE : Palette.INK_2)
        }
        .width(28)
        .height(28)
        .margin({ top: 1 })
        .backgroundColor(this.playingLineId === line.id ? Palette.LIVE_SOFT : Palette.SURFACE_SUNK)
        .enabled(this.phase === 'idle' || this.playingLineId === line.id)
        .opacity(this.phase === 'idle' || this.playingLineId === line.id ? 1 : 0.4)
        .accessibilityText(this.playingLineId === line.id ? '停止播放' : '播放这句')
        .onClick((): void => this.togglePlayLine(line))
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 8, bottom: 8 })
  }

  /**
   * The single live row: always present during a session, so partial results update in place.
   * When a sentence is committed it moves into LineItem with identical metrics, only the colour changes.
   */
  @Builder
  LiveItem() {
    Row({ space: 14 }) {
      Row() {
        Circle().width(7).height(7).fill(this.phase === 'finishing' ? Palette.INK_3 : Palette.LIVE)
      }
      .width(40)
      .height(29)
      if (this.liveText.length > 0) {
        Text() {
          Span(this.liveText.substring(0, this.liveSettled)).fontColor(Palette.INK)
          Span(this.liveText.substring(this.liveSettled)).fontColor(Palette.INK_3)
        }
        .layoutWeight(1)
        .fontSize(18)
        .lineHeight(29)
        .opacity(this.liveOpacity)
      } else {
        Text(this.liveHint())
          .layoutWeight(1)
          .fontSize(18)
          .lineHeight(29)
          .fontColor(Palette.INK_3)
      }
    }
    .width('100%')
    .alignItems(VerticalAlign.Top)
    .padding({ top: 8, bottom: 8 })
  }

  private liveHint(): string {
    if (this.phase === 'connecting') return '正在准备…';
    if (this.phase === 'finishing') return '正在整理最后一句…';
    return '正在聆听…';
  }

  @Builder
  DividerItem(line: TranscriptLine) {
    Row({ space: 10 }) {
      Column().height(1).layoutWeight(1).backgroundColor(Palette.LINE)
      Text(`${line.time} 新的识别`).fontSize(11).fontColor(Palette.INK_3)
      Column().height(1).layoutWeight(1).backgroundColor(Palette.LINE)
    }
    .width('100%')
    .padding({ top: 14, bottom: 10 })
  }

  // ---- dock ----------------------------------------------------------------

  @Builder
  Dock() {
    Column({ space: 12 }) {
      Row() {
        Text(this.phase === 'idle' ? '' : this.formatClock(this.elapsedSec))
          .fontSize(13)
          .fontColor(Palette.INK_2)
          .fontFeature('"tnum" on')
          .width(72)
          .textAlign(TextAlign.Start)
        Blank()
        this.MicButton()
        Blank()
        Column() {
          if (this.phase === 'listening') {
            LevelBars({ levels: this.levels.slice(LEVEL_BARS - 12), color: Palette.LIVE, barHeight: 22 })
          }
        }
        .width(72)
        .alignItems(HorizontalAlign.End)
      }
      .width('100%')
      .padding({ left: 28, right: 28 })

      Text(this.dockHint()).fontSize(13).fontColor(Palette.INK_2)
    }
    .width('100%')
    .padding({ top: 26, bottom: px2vp(this.insetBottomPx) + 14 })
    .linearGradient({ angle: 180, colors: [['#00F5F4F0', 0], ['#F2F5F4F0', 0.28], [Palette.PAPER, 1]] })
  }

  @Builder
  MicButton() {
    Stack() {
      if (this.phase === 'listening') {
        Circle()
          .width(84).height(84)
          .fill(Palette.LIVE)
          .opacity(0.16)
          .scale({ x: 1 + this.level * 0.5, y: 1 + this.level * 0.5 })
          .animation({ duration: 120, curve: Curve.EaseOut })
        Circle()
          .width(84).height(84)
          .fill(Palette.LIVE)
          .opacity(this.breathe ? 0 : 0.22)
          .scale({ x: this.breathe ? 1.7 : 1, y: this.breathe ? 1.7 : 1 })
          .animation({ duration: 1600, curve: Curve.EaseOut, iterations: -1, playMode: PlayMode.Normal })
          .onAppear((): void => { this.breathe = true; })
          .onDisAppear((): void => { this.breathe = false; })
      }
      Button({ type: ButtonType.Circle, stateEffect: true }) {
        if (this.phase === 'connecting' || this.phase === 'finishing') {
          LoadingProgress().width(34).height(34).color(Color.White)
        } else if (this.phase === 'listening') {
          Image($r('app.media.ic_stop')).width(30).height(30).fillColor(Color.White)
        } else {
          Image($r('app.media.ic_mic')).width(32).height(32).fillColor(Color.White)
        }
      }
      .width(84)
      .height(84)
      .backgroundColor(this.phase === 'idle' ? Palette.BRAND : (this.phase === 'finishing' ? Palette.INK_2 : Palette.LIVE))
      .shadow({ radius: 24, color: this.phase === 'idle' ? '#664A4FE6' : '#55EE7A3B', offsetY: 8 })
      .enabled(this.phase !== 'finishing' && this.recordingSlot.length === 0 && !this.registering)
      .accessibilityText(this.phase === 'idle' ? '开始识别' : '结束识别')
      .onClick((): void => this.onMicTap())
    }
    .width(140)
    .height(100)
  }

  // ---- settings sheet ------------------------------------------------------

  @Builder
  SettingsSheet() {
    Column({ space: 0 }) {
      Row() {
        Text('设置').fontSize(20).fontWeight(FontWeight.Bold).fontColor(Palette.INK)
        Blank()
        Button({ type: ButtonType.Circle }) {
          Image($r('app.media.ic_close')).width(18).height(18).fillColor(Palette.INK_2)
        }
        .width(36).height(36).backgroundColor(Palette.SURFACE_SUNK)
        .onClick((): void => { this.settingsOpen = false; })
      }
      .width('100%')

      Text('识别语种').fontSize(13).fontColor(Palette.INK_3).margin({ top: 22, bottom: 10 })
      Row({ space: 6 }) {
        this.LanguageOption('zh', '中文')
        this.LanguageOption('zh_en', '中英混合')
      }
      .width('100%')
      .padding(4)
      .borderRadius(14)
      .backgroundColor(Palette.SURFACE_SUNK)

      Text('当前声纹的名字').fontSize(13).fontColor(Palette.INK_3).margin({ top: 22, bottom: 10 })
      TextInput({ text: this.profileName, placeholder: '例如：张三' })
        .height(48)
        .fontSize(15)
        .borderRadius(14)
        .backgroundColor(Palette.SURFACE_SUNK)
        .maxLength(12)
        .onChange((value: string): void => {
          if (value.trim().length === 0) return;
          this.profileName = value.trim();
          AppPrefs.setProfileName(this.context, value);
          this.profiles = AppPrefs.profiles(this.context);
        })

      Row() {
        Column({ space: 3 }) {
          Text('句尾播放按钮').fontSize(15).fontColor(Palette.INK)
          Text('每句识别结果可回放对应的原声').fontSize(12).fontColor(Palette.INK_3)
        }
        .alignItems(HorizontalAlign.Start)
        .layoutWeight(1)
        Toggle({ type: ToggleType.Switch, isOn: this.sentencePlayback })
          .selectedColor(Palette.BRAND)
          .onChange((isOn: boolean): void => {
            this.sentencePlayback = isOn;
            AppPrefs.setSentencePlayback(this.context, isOn);
            if (!isOn) {
              this.player.stop();
              this.playingLineId = -1;
            }
          })
      }
      .width('100%')
      .margin({ top: 22 })

      Text('服务地址').fontSize(13).fontColor(Palette.INK_3).margin({ top: 22, bottom: 10 })
      TextInput({ text: this.draftBase, placeholder: 'https://' })
        .height(48)
        .fontSize(15)
        .borderRadius(14)
        .backgroundColor(Palette.SURFACE_SUNK)
        .type(InputType.URL)
        .enabled(this.phase === 'idle' && !this.registering)
        .onChange((value: string): void => { this.draftBase = value; })
      Text('更换服务地址后，声纹会自动重新注册。').fontSize(12).fontColor(Palette.INK_3).margin({ top: 8 })

      Button('保存', { type: ButtonType.Capsule })
        .width('100%')
        .height(50)
        .margin({ top: 28 })
        .fontSize(16)
        .fontWeight(FontWeight.Medium)
        .backgroundColor(Palette.INK)
        .onClick((): void => this.saveSettings())

      // Deliberately low-key: Speaker VAD ("强过滤") is on by default and rarely needs changing.
      Row({ space: 6 }) {
        Text('强过滤').fontSize(12).fontColor(Palette.INK_3)
        Toggle({ type: ToggleType.Switch, isOn: this.strongFilter })
          .selectedColor(Palette.INK_3)
          .scale({ x: 0.7, y: 0.7 })
          .enabled(this.phase === 'idle')
          .onChange((isOn: boolean): void => {
            this.strongFilter = isOn;
            AppPrefs.setStrongFilter(this.context, isOn);
          })
      }
      .margin({ top: 18 })
      .alignSelf(ItemAlign.Center)

      Text(`Amphion · ${this.appVersion}`).fontSize(12).fontColor(Palette.INK_3).margin({ top: 16 }).alignSelf(ItemAlign.Center)
    }
    .width('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ left: 24, right: 24, top: 18, bottom: 28 })
  }

  @Builder
  LanguageOption(value: RecognitionLanguage, label: string) {
    Text(label)
      .fontSize(15)
      .fontWeight(this.language === value ? FontWeight.Medium : FontWeight.Normal)
      .fontColor(this.language === value ? Palette.INK : Palette.INK_2)
      .textAlign(TextAlign.Center)
      .layoutWeight(1)
      .height(40)
      .borderRadius(11)
      .backgroundColor(this.language === value ? Palette.SURFACE : Color.Transparent)
      .shadow(this.language === value ? { radius: 8, color: '#14000000', offsetY: 2 } : { radius: 0, color: Color.Transparent })
      .onClick((): void => {
        this.language = value;
        AppPrefs.setLanguage(this.context, value);
      })
  }

  private saveSettings(): void {
    const base = this.draftBase.trim().replace(/\/+$/, '');
    if (!/^https?:\/\/[^\s/]+/.test(base)) {
      this.toast('请输入有效的服务地址');
      return;
    }
    if (base !== this.cloudBase) {
      this.cloudBase = base;
      AppPrefs.setCloudBase(this.context, base);
      this.cloudId = '';
      AppPrefs.setCloudEnrollmentId(this.context, '');
      this.cloudSync = 'unknown';
      this.lastAutoSyncAt = 0;
      this.refreshCloudStatus();
    }
    this.settingsOpen = false;
    this.toast('设置已保存');
  }
}
