import type { SpeakParams } from './TtsApiTypes';

export class AudioTransforms {
  static apply(source: ArrayBuffer, params: SpeakParams): ArrayBuffer {
    const pitch = params.pitch ?? 1.0;
    const speed = params.speed ?? 1.0;
    const volume = params.volume ?? 1.0;
    if (pitch === 1.0 && speed === 1.0 && volume === 1.0) {
      return source;
    }
    let samples = new Int16Array(source.slice(0));
    if (pitch !== 1.0) {
      samples = AudioTransforms.applyPitch(samples, clampNumber(pitch, 0.5, 2.0));
    }
    if (speed !== 1.0) {
      samples = AudioTransforms.applySpeed(samples, clampNumber(speed, 0.5, 2.0));
    }
    if (volume !== 1.0) {
      samples = AudioTransforms.applyVolume(samples, clampNumber(volume, 0.0, 2.0));
    }
    return samples.buffer as ArrayBuffer;
  }

  static applyPitchAndVolume(source: ArrayBuffer, params: SpeakParams): ArrayBuffer {
    const pitch = params.pitch ?? 1.0;
    const volume = params.volume ?? 1.0;
    if (pitch === 1.0 && volume === 1.0) {
      return source;
    }
    let samples = new Int16Array(source.slice(0));
    if (pitch !== 1.0) {
      samples = AudioTransforms.applyPitch(samples, clampNumber(pitch, 0.5, 2.0));
    }
    if (volume !== 1.0) {
      samples = AudioTransforms.applyVolume(samples, clampNumber(volume, 0.0, 2.0));
    }
    return samples.buffer as ArrayBuffer;
  }

  private static applyPitch(input: Int16Array, pitch: number): Int16Array {
    if (input.length === 0) {
      return input;
    }
    const shifted = AudioTransforms.resampleToLength(input, Math.max(1, Math.round(input.length / pitch)));
    return AudioTransforms.resampleToLength(shifted, input.length);
  }

  private static applySpeed(input: Int16Array, speed: number): Int16Array {
    if (input.length === 0) {
      return input;
    }
    return AudioTransforms.resampleToLength(input, Math.max(1, Math.round(input.length / speed)));
  }

  private static applyVolume(input: Int16Array, volume: number): Int16Array {
    const output = new Int16Array(input.length);
    for (let index = 0; index < input.length; index += 1) {
      const scaled = Math.round(input[index] * volume);
      output[index] = clampInt16(scaled);
    }
    return output;
  }

  private static resampleToLength(input: Int16Array, targetLength: number): Int16Array {
    if (input.length === targetLength) {
      return new Int16Array(input.slice().buffer);
    }
    if (targetLength <= 1) {
      return new Int16Array([input[0]]);
    }
    const output = new Int16Array(targetLength);
    const ratio = (input.length - 1) / (targetLength - 1);
    for (let index = 0; index < targetLength; index += 1) {
      const position = index * ratio;
      const left = Math.min(input.length - 1, Math.floor(position));
      const right = Math.min(input.length - 1, left + 1);
      const fraction = position - left;
      const value = input[left] + Math.round((input[right] - input[left]) * fraction);
      output[index] = clampInt16(value);
    }
    return output;
  }
}

export function lengthScaleForSpeed(speed: number): number {
  const clampedSpeed = Number.isFinite(speed) ? clampNumber(speed, 0.5, 2.0) : 1.0;
  return clampNumber(1.0 / clampedSpeed, 0.5, 2.0);
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value));
}

function clampInt16(value: number): number {
  return Math.min(32767, Math.max(-32768, value));
}
