import { preferences } from '@kit.ArkData';
import { util } from '@kit.ArkTS';

const STORE_NAME = 'amphion_voice';
const KEY_LOCAL_ID = 'local_voiceprint_id';
const KEY_CLOUD_ID = 'cloud_enrollment_id';
const KEY_PROFILE_KEY = 'voiceprint_profile_key';
const KEY_PROFILE_NAME = 'voiceprint_profile_name';
const KEY_ENGINE = 'engine';
const KEY_CLOUD_BASE = 'cloud_base';
const KEY_LANGUAGE = 'language';
const KEY_SENTENCE_PLAYBACK = 'sentence_playback';
const KEY_STRONG_FILTER = 'strong_filter';
const KEY_PROFILES = 'voiceprint_profiles';
const KEY_ACTIVE_PROFILE = 'active_voiceprint_profile';

/** One enrolled person. Each has its own recordings, on-device id, cloud id and cloud key. */
export class VoiceprintProfile {
  id: string = '';
  name: string = '';
  key: string = '';
  localId: string = '';
  cloudId: string = '';
  createdAt: number = 0;
}

export const DEFAULT_CLOUD_BASE = 'https://113.46.211.82';

export type EngineKind = 'local' | 'cloud';
export type RecognitionLanguage = 'zh' | 'zh_en';

/** Small, synchronous app settings. The voiceprint audio itself lives in VoiceprintSamples. */
export class AppPrefs {
  private static store(context: Context): preferences.Preferences {
    return preferences.getPreferencesSync(context, { name: STORE_NAME });
  }

  private static getString(context: Context, key: string, fallback: string): string {
    return (AppPrefs.store(context).getSync(key, fallback) as string).trim();
  }

  private static putString(context: Context, key: string, value: string): void {
    const store = AppPrefs.store(context);
    store.putSync(key, value);
    store.flush();
  }

  // ---- voiceprint profiles ----------------------------------------------------------
  // The accessors below (localVoiceprintId, cloudEnrollmentId, profileKey, profileName) always act on
  // the active profile, so the recognition and registration flow stays single-target.

  static profiles(context: Context): VoiceprintProfile[] {
    const raw = AppPrefs.getString(context, KEY_PROFILES, '');
    if (raw.length > 0) {
      try {
        return JSON.parse(raw) as VoiceprintProfile[];
      } catch (_e) {
        return [];
      }
    }
    // First run after multi-profile support: carry the single legacy voiceprint over.
    const legacyLocal = AppPrefs.getString(context, KEY_LOCAL_ID, '');
    const legacyCloud = AppPrefs.getString(context, KEY_CLOUD_ID, '');
    const legacyKey = AppPrefs.getString(context, KEY_PROFILE_KEY, '');
    const list: VoiceprintProfile[] = [];
    if (legacyLocal.length > 0 || legacyCloud.length > 0 || legacyKey.length > 0) {
      const profile = AppPrefs.newProfile(AppPrefs.getString(context, KEY_PROFILE_NAME, '') || '我');
      profile.id = 'legacy';
      profile.localId = legacyLocal;
      profile.cloudId = legacyCloud;
      if (legacyKey.length > 0) profile.key = legacyKey;
      list.push(profile);
      AppPrefs.putString(context, KEY_ACTIVE_PROFILE, profile.id);
    }
    AppPrefs.saveProfiles(context, list);
    return list;
  }

  static activeProfile(context: Context): VoiceprintProfile | undefined {
    const list = AppPrefs.profiles(context);
    const id = AppPrefs.getString(context, KEY_ACTIVE_PROFILE, '');
    return list.find((p: VoiceprintProfile): boolean => p.id === id) ?? list[0];
  }

  static setActiveProfile(context: Context, id: string): void {
    AppPrefs.putString(context, KEY_ACTIVE_PROFILE, id);
  }

  /** Adds a profile and makes it active. */
  static addProfile(context: Context, name: string): VoiceprintProfile {
    const list = AppPrefs.profiles(context);
    const profile = AppPrefs.newProfile(name);
    list.push(profile);
    AppPrefs.saveProfiles(context, list);
    AppPrefs.setActiveProfile(context, profile.id);
    return profile;
  }

  /** Forgets a profile (its registrations must be removed by the caller). Picks another as active. */
  static removeProfile(context: Context, id: string): void {
    const list = AppPrefs.profiles(context).filter((p: VoiceprintProfile): boolean => p.id !== id);
    AppPrefs.saveProfiles(context, list);
    if (AppPrefs.getString(context, KEY_ACTIVE_PROFILE, '') === id) {
      AppPrefs.setActiveProfile(context, list.length > 0 ? list[0].id : '');
    }
  }

  private static newProfile(name: string): VoiceprintProfile {
    const profile = new VoiceprintProfile();
    profile.id = `p${Date.now().toString(36)}`;
    profile.name = name.trim().length > 0 ? name.trim() : '我';
    profile.key = `amphion-${util.generateRandomUUID(false).replace(/-/g, '')}`;
    profile.createdAt = Date.now();
    return profile;
  }

  private static saveProfiles(context: Context, list: VoiceprintProfile[]): void {
    AppPrefs.putString(context, KEY_PROFILES, JSON.stringify(list));
  }

  /** Applies a change to the active profile, creating a first profile if there is none yet. */
  private static updateActive(context: Context, change: (p: VoiceprintProfile) => void): VoiceprintProfile {
    let list = AppPrefs.profiles(context);
    let active = AppPrefs.activeProfile(context);
    if (active === undefined) {
      active = AppPrefs.addProfile(context, '我');
      list = AppPrefs.profiles(context);
    }
    const id = active.id;
    const target = list.find((p: VoiceprintProfile): boolean => p.id === id) as VoiceprintProfile;
    change(target);
    AppPrefs.saveProfiles(context, list);
    return target;
  }

  static localVoiceprintId(context: Context): string {
    return AppPrefs.activeProfile(context)?.localId ?? '';
  }

  static setLocalVoiceprintId(context: Context, id: string): void {
    AppPrefs.updateActive(context, (p: VoiceprintProfile): void => { p.localId = id; });
  }

  static cloudEnrollmentId(context: Context): string {
    return AppPrefs.activeProfile(context)?.cloudId ?? '';
  }

  static setCloudEnrollmentId(context: Context, id: string): void {
    AppPrefs.updateActive(context, (p: VoiceprintProfile): void => { p.cloudId = id; });
  }

  /** Per-profile key that groups that person's cloud enrollment. Never shown in the UI. */
  static profileKey(context: Context): string {
    return AppPrefs.updateActive(context, (_p: VoiceprintProfile): void => {}).key;
  }

  static profileName(context: Context): string {
    return AppPrefs.activeProfile(context)?.name ?? '';
  }

  static setProfileName(context: Context, name: string): void {
    if (name.trim().length === 0) return;
    AppPrefs.updateActive(context, (p: VoiceprintProfile): void => { p.name = name.trim(); });
  }

  static engine(context: Context): EngineKind {
    return AppPrefs.getString(context, KEY_ENGINE, 'local') === 'cloud' ? 'cloud' : 'local';
  }

  static setEngine(context: Context, engine: EngineKind): void {
    AppPrefs.putString(context, KEY_ENGINE, engine);
  }

  static cloudBase(context: Context): string {
    const value = AppPrefs.getString(context, KEY_CLOUD_BASE, DEFAULT_CLOUD_BASE);
    return value.length > 0 ? value.replace(/\/+$/, '') : DEFAULT_CLOUD_BASE;
  }

  static setCloudBase(context: Context, base: string): void {
    AppPrefs.putString(context, KEY_CLOUD_BASE, base.trim().replace(/\/+$/, ''));
  }

  static language(context: Context): RecognitionLanguage {
    return AppPrefs.getString(context, KEY_LANGUAGE, 'zh') === 'zh_en' ? 'zh_en' : 'zh';
  }

  static setLanguage(context: Context, language: RecognitionLanguage): void {
    AppPrefs.putString(context, KEY_LANGUAGE, language);
  }

  /**
   * 「强过滤」= Speaker VAD. On by default. When off, recognition requests carry no Speaker VAD
   * parameters at all (the engine's own default applies), rather than an explicit false.
   */
  static strongFilter(context: Context): boolean {
    return AppPrefs.store(context).getSync(KEY_STRONG_FILTER, true) as boolean;
  }

  static setStrongFilter(context: Context, enabled: boolean): void {
    const store = AppPrefs.store(context);
    store.putSync(KEY_STRONG_FILTER, enabled);
    store.flush();
  }

  /** Whether each recognized sentence offers playback of its audio. On by default. */
  static sentencePlayback(context: Context): boolean {
    return AppPrefs.store(context).getSync(KEY_SENTENCE_PLAYBACK, true) as boolean;
  }

  static setSentencePlayback(context: Context, enabled: boolean): void {
    const store = AppPrefs.store(context);
    store.putSync(KEY_SENTENCE_PLAYBACK, enabled);
    store.flush();
  }
}
