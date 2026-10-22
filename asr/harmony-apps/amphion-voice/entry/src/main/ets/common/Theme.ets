/**
 * Amphion visual tokens. Warm paper surfaces, ink typography, one indigo brand accent;
 * amber marks live capture and green marks a verified voiceprint. Nothing else carries colour.
 */
export class Palette {
  static readonly PAPER: string = '#F5F4F0';
  static readonly SURFACE: string = '#FFFFFF';
  static readonly SURFACE_SUNK: string = '#F0EEE8';
  static readonly LINE: string = '#E6E2D9';
  static readonly INK: string = '#14161F';
  static readonly INK_2: string = '#4A4F5E';
  static readonly INK_3: string = '#8B8F9B';
  static readonly NIGHT: string = '#11131C';
  static readonly NIGHT_2: string = '#1C1F33';
  static readonly NIGHT_LINE: string = '#2A2E47';
  static readonly ON_NIGHT: string = '#F4F4FA';
  static readonly ON_NIGHT_2: string = '#A3A7C2';
  static readonly BRAND: string = '#4A4FE6';
  static readonly BRAND_SOFT: string = '#ECECFD';
  static readonly BRAND_GLOW: string = '#8C90FF';
  static readonly LIVE: string = '#EE7A3B';
  static readonly LIVE_SOFT: string = '#FDEEE4';
  static readonly OK: string = '#13906B';
  static readonly OK_SOFT: string = '#E2F3EC';
  static readonly WARN: string = '#B4541A';
  static readonly WARN_SOFT: string = '#FBEFE3';
  static readonly DANGER: string = '#C8372D';
}

export class Space {
  static readonly GUTTER: number = 20;
  static readonly CARD_PAD: number = 20;
  static readonly RADIUS_CARD: number = 24;
  static readonly RADIUS_CHIP: number = 999;
}

export class Motion {
  static readonly FAST: number = 160;
  static readonly BASE: number = 240;
}
