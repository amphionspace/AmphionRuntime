import { preferences } from '@kit.ArkData';

const STORE_NAME = 'amphion_asr_demo';
const KEY_VOICEPRINT_ID = 'voiceprint_id';
const KEY_HOTWORDS = 'user_hotwords';
const KEY_POLICE_ENHANCEMENT = 'police_enhancement';
const KEY_TARGET_SPEAKER_ENHANCEMENT = 'target_speaker_enhancement';

/**
 * Lightweight persistence for the demo: the registered voiceprint id and the user's custom hotwords.
 * Hotwords are stored newline-joined (passed to the SDK as sysGeneralLexicon). Mirrors Android DemoPrefs.
 */
export class DemoPrefs {
  private static store(context: Context): preferences.Preferences {
    return preferences.getPreferencesSync(context, { name: STORE_NAME });
  }

  static getVoiceprintId(context: Context): string {
    const id = DemoPrefs.store(context).getSync(KEY_VOICEPRINT_ID, '') as string;
    return id.trim();
  }

  static setVoiceprintId(context: Context, id: string): void {
    const store = DemoPrefs.store(context);
    store.putSync(KEY_VOICEPRINT_ID, id);
    store.flush();
  }

  static getUserHotwords(context: Context): string[] {
    const raw = DemoPrefs.store(context).getSync(KEY_HOTWORDS, '') as string;
    if (raw.length === 0) return [];
    return raw.split('\n').map((s: string): string => s.trim()).filter((s: string): boolean => s.length > 0);
  }

  static setUserHotwords(context: Context, words: string[]): void {
    const normalized = words.map((s: string): string => s.trim()).filter((s: string): boolean => s.length > 0);
    const store = DemoPrefs.store(context);
    store.putSync(KEY_HOTWORDS, normalized.join('\n'));
    store.flush();
  }

  static getPoliceEnhancementEnabled(context: Context): boolean {
    return DemoPrefs.store(context).getSync(KEY_POLICE_ENHANCEMENT, true) as boolean;
  }

  static setPoliceEnhancementEnabled(context: Context, enabled: boolean): void {
    const store = DemoPrefs.store(context);
    store.putSync(KEY_POLICE_ENHANCEMENT, enabled);
    store.flush();
  }

  static getTargetSpeakerEnhancementEnabled(context: Context): boolean {
    return DemoPrefs.store(context).getSync(KEY_TARGET_SPEAKER_ENHANCEMENT, false) as boolean;
  }

  static setTargetSpeakerEnhancementEnabled(context: Context, enabled: boolean): void {
    const store = DemoPrefs.store(context);
    store.putSync(KEY_TARGET_SPEAKER_ENHANCEMENT, enabled);
    store.flush();
  }
}
