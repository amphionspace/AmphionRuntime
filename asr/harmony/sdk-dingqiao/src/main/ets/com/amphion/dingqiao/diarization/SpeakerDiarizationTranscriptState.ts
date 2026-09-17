export interface DiarizationTranscriptInput {
  rawText: string;
  text: string;
  tokens: string[];
  tokenTimesMs: number[];
  beginTime: number;
  endTime: number;
  audioEndTime?: number;
}

export interface SpeakerTimelineTurn {
  beginTime: number;
  endTime: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  confidence?: number;
  overlap?: boolean;
  evidenceKey?: string;
  secondaryEvidenceKeys?: string[];
  // One ID per acoustic channel, even when display IDs currently collapse.
  secondaryEvidenceSpeakerIds?: string[];
}

export interface DiarizationTranscriptUpdate extends SpeakerTimelineTurn {
  utteranceId: string;
  revision: number;
  confidence: number;
}

export interface DiarizedTranscriptUtterance extends SpeakerTimelineTurn {
  sourceUtteranceId: string;
  utteranceId: string;
  rawText: string;
  text: string;
  overlap: boolean;
  speakerInferred?: boolean;
}

interface StoredUtterance extends DiarizationTranscriptInput {
  utteranceId: string;
  revision: number;
  speakerId: string;
  secondarySpeakerIds: string[];
}

const UNKNOWN_SPEAKER = 'UNKNOWN';
// One current inference hop. See delivery/harmony-dingqiao/docs/UNKNOWN_SPEAKER_BACKFILL.md for the
// measured bounded/unbounded comparison; this is not an identity threshold.
const MAX_UNKNOWN_BACKFILL_MS = 2_500;

function overlapMs(beginA: number, endA: number, beginB: number, endB: number): number {
  return Math.max(0, Math.min(endA, endB) - Math.max(beginA, beginB));
}

function sameStrings(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  for (let i = 0; i < left.length; i++) {
    if (left[i] !== right[i]) return false;
  }
  return true;
}

function visibleSecondaryIds(ids: string[], primary: string): string[] {
  return ids.filter((id: string, index: number, all: string[]): boolean =>
    id !== primary && all.indexOf(id) === index);
}

// Align only inserted punctuation/spacing. Lexical rewrites (including ITN) must
// keep the original paragraph until the postprocessor supplies a timed mapping.
function tokenTextBoundaries(tokens: string[], text: string): number[] | undefined {
  const inserted = ' ,.!?，。！？、;；:：\t\r\n';
  const boundaries: number[] = [0];
  let cursor = 0;
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.length === 0) return undefined;
    for (let character = 0; character < token.length; character++) {
      while (cursor < text.length && text[cursor] !== token[character] &&
        inserted.indexOf(text[cursor]) >= 0) cursor++;
      if (cursor >= text.length || text[cursor] !== token[character]) return undefined;
      // Keep inserted sentence punctuation with the preceding token.
      if (index > 0 && character === 0) boundaries.push(cursor);
      cursor++;
    }
  }
  while (cursor < text.length && inserted.indexOf(text[cursor]) >= 0) cursor++;
  if (cursor !== text.length) return undefined;
  boundaries.push(cursor);
  return boundaries;
}

interface TimedTranscriptTokens {
  tokens: string[];
  times: number[];
}

// Byte alphabet and separator semantics match sherpa-onnx/csrc/{bbpe,symbol-table}.cc.
// A UTF-8 character may span tokens; its first byte owns its timestamp.
function decodedTranscriptTokens(rawText: string, tokens: string[],
  times: number[]): TimedTranscriptTokens | undefined {
  if (tokens.length !== times.length || tokens.join('') === rawText) return undefined;
  const alphabet = "ĀāĂăĄąĆćĈĉĊċČčĎďĐđĒēĔĕĖėĘęĚěĜĝĞğ !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~ĠġĢģĤĥĦħĨĩĪīĬĭĮįİıĴĵĶķĸĹĺĻļĽľŁłŃńŅņŇňŊŋŌōŎŏŐőŒœŔŕŖŗŘřŚśŜŝŞşŠšŢţŤťŦŧŨũŪūŬŭŮůŰűŲųŴŵŶŷŸŹźŻżŽžƀƁƂƃƄƅƆƇƈƉƊƋƌƍƎƏƐƑƒƓƔƕƖƗƘƙƚƛƜƝƞƟƠơƢƣƤƥƦ";
  const bytes: number[] = [];
  const owners: number[] = [];
  for (let index = 0; index < tokens.length; index++) {
    for (let offset = 0; offset < tokens[index].length; offset++) {
      const character = tokens[index][offset];
      if (character === '▁') {
        const last = bytes.length > 0 ? bytes[bytes.length - 1] : -1;
        if (last > 32 && last <= 126) {
          bytes.push(32);
          owners.push(times[index]);
        }
        continue;
      }
      const value = character === '⁇' ? 32 : alphabet.indexOf(character);
      if (value < 0) return undefined;
      bytes.push(value);
      owners.push(times[index]);
    }
  }
  const decoded: string[] = [];
  const decodedTimes: number[] = [];
  let byteOffset = 0;
  for (let index = 0; index < rawText.length;) {
    const point = rawText.codePointAt(index) ?? 0;
    if (point >= 0xD800 && point <= 0xDFFF) return undefined;
    const width = point > 0xFFFF ? 2 : 1;
    const encoded: number[] = point < 0x80 ? [point] : point < 0x800 ?
      [0xC0 | (point >> 6), 0x80 | (point & 63)] : point < 0x10000 ?
      [0xE0 | (point >> 12), 0x80 | ((point >> 6) & 63), 0x80 | (point & 63)] :
      [0xF0 | (point >> 18), 0x80 | ((point >> 12) & 63),
        0x80 | ((point >> 6) & 63), 0x80 | (point & 63)];
    for (let part = 0; part < encoded.length; part++) {
      if (bytes[byteOffset + part] !== encoded[part]) return undefined;
    }
    decoded.push(rawText.slice(index, index + width));
    decodedTimes.push(owners[byteOffset]);
    byteOffset += encoded.length;
    index += width;
  }
  return byteOffset === bytes.length ? { tokens: decoded, times: decodedTimes } : undefined;
}

export class SpeakerDiarizationTranscriptState {
  private readonly utterances: StoredUtterance[] = [];
  private nextUtteranceId: number = 1;
  private readonly turns: SpeakerTimelineTurn[] = [];

  addUtterance(input: DiarizationTranscriptInput): string {
    const decoded = decodedTranscriptTokens(input.rawText, input.tokens, input.tokenTimesMs);
    const utteranceId = `u${this.nextUtteranceId++}`;
    const assignment = this.assignmentFor(input.beginTime, input.endTime);
    this.utterances.push({
      utteranceId,
      rawText: input.rawText,
      text: input.text,
      tokens: decoded?.tokens ?? input.tokens.slice(),
      tokenTimesMs: decoded?.times ?? input.tokenTimesMs.slice(),
      beginTime: input.beginTime,
      endTime: input.endTime,
      audioEndTime: input.audioEndTime,
      revision: 0,
      speakerId: assignment.speakerId,
      secondarySpeakerIds: assignment.secondarySpeakerIds,
    });
    return utteranceId;
  }

  currentAssignment(utteranceId: string): DiarizationTranscriptUpdate | undefined {
    const utterance = this.utterances.find(
      (candidate: StoredUtterance): boolean => candidate.utteranceId === utteranceId);
    if (utterance === undefined) return undefined;
    return {
      utteranceId: utterance.utteranceId,
      revision: utterance.revision,
      speakerId: utterance.speakerId,
      secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
      beginTime: utterance.beginTime,
      endTime: utterance.endTime,
      confidence: this.assignmentFor(utterance.beginTime, utterance.endTime).confidence,
    };
  }

  applySpeakerTurns(newTurns: SpeakerTimelineTurn[]): DiarizationTranscriptUpdate[] {
    if (newTurns.length === 0) return [];
    for (let i = 0; i < newTurns.length; i++) {
      const evidenceIds = newTurns[i].secondaryEvidenceSpeakerIds ?? newTurns[i].secondarySpeakerIds;
      this.turns.push({
        beginTime: newTurns[i].beginTime,
        endTime: newTurns[i].endTime,
        speakerId: newTurns[i].speakerId,
        secondarySpeakerIds: visibleSecondaryIds(evidenceIds, newTurns[i].speakerId),
        confidence: newTurns[i].confidence,
        overlap: newTurns[i].overlap,
        evidenceKey: newTurns[i].evidenceKey,
        secondaryEvidenceKeys: newTurns[i].secondaryEvidenceKeys?.slice(),
        secondaryEvidenceSpeakerIds: evidenceIds.slice(),
      });
    }

    const updates: DiarizationTranscriptUpdate[] = [];
    for (let i = 0; i < this.utterances.length; i++) {
      const utterance = this.utterances[i];
      if (!this.intersectsAny(utterance, newTurns)) continue;
      const assignment = this.assignmentFor(utterance.beginTime, utterance.endTime);
      if (assignment.speakerId === utterance.speakerId &&
        sameStrings(assignment.secondarySpeakerIds, utterance.secondarySpeakerIds)) continue;
      utterance.speakerId = assignment.speakerId;
      utterance.secondarySpeakerIds = assignment.secondarySpeakerIds;
      utterance.revision += 1;
      updates.push({
        utteranceId: utterance.utteranceId,
        revision: utterance.revision,
        speakerId: utterance.speakerId,
        secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
        beginTime: utterance.beginTime,
        endTime: utterance.endTime,
        confidence: assignment.confidence,
      });
    }
    return updates;
  }

  finalUtterances(throughTime: number = Number.POSITIVE_INFINITY): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    for (let i = 0; i < this.utterances.length; i++) {
      const utterance = this.utterances[i];
      if ((utterance.audioEndTime ?? utterance.endTime) > throughTime) continue;
      const boundaries = utterance.tokens.length > 0 &&
        utterance.tokens.length === utterance.tokenTimesMs.length ?
        tokenTextBoundaries(utterance.tokens, utterance.text) : undefined;
      if (boundaries === undefined) {
        result.push(this.unsplitUtterance(utterance));
        continue;
      }
      const split = this.splitByTokenSpeaker(utterance, boundaries);
      if (split.map((item: DiarizedTranscriptUtterance): string => item.text).join('') !==
        utterance.text) {
        result.push(this.unsplitUtterance(utterance));
      } else {
        result.push(...split);
      }
    }
    return result;
  }

  commitThrough(endTime: number): DiarizedTranscriptUtterance[] {
    const result = this.finalUtterances(endTime);
    for (let i = this.utterances.length - 1; i >= 0; i--) {
      if ((this.utterances[i].audioEndTime ?? this.utterances[i].endTime) <= endTime) {
        this.utterances.splice(i, 1);
      }
    }
    // Keep a crossing utterance's timeline until the original ASR final is complete.
    let retainFrom = endTime;
    for (const utterance of this.utterances) retainFrom = Math.min(retainFrom, utterance.beginTime);
    for (let i = this.turns.length - 1; i >= 0; i--) {
      if (this.turns[i].endTime <= retainFrom) this.turns.splice(i, 1);
      else this.turns[i].beginTime = Math.max(this.turns[i].beginTime, retainFrom);
    }
    return result;
  }

  allTurns(): SpeakerTimelineTurn[] {
    return this.turns.map((turn) => ({
      beginTime: turn.beginTime,
      endTime: turn.endTime,
      speakerId: turn.speakerId,
      secondarySpeakerIds: turn.secondarySpeakerIds.slice(),
      confidence: turn.confidence,
      overlap: turn.overlap,
      evidenceKey: turn.evidenceKey,
      secondaryEvidenceKeys: turn.secondaryEvidenceKeys?.slice(),
      secondaryEvidenceSpeakerIds: turn.secondaryEvidenceSpeakerIds?.slice(),
    }));
  }

  applySpeakerRemap(remap: Record<string, string>, fromTime: number = 0): DiarizationTranscriptUpdate[] {
    for (let i = 0; i < this.turns.length; i++) {
      if (this.turns[i].endTime < fromTime) continue;
      const turn = this.turns[i];
      turn.speakerId = remap[turn.speakerId] ?? turn.speakerId;
      turn.secondaryEvidenceSpeakerIds = (turn.secondaryEvidenceSpeakerIds ?? turn.secondarySpeakerIds)
        .map((speakerId: string): string => remap[speakerId] ?? speakerId);
      turn.secondarySpeakerIds = visibleSecondaryIds(turn.secondaryEvidenceSpeakerIds, turn.speakerId);
    }
    const updates: DiarizationTranscriptUpdate[] = [];
    for (let i = 0; i < this.utterances.length; i++) {
      const utterance = this.utterances[i];
      if (utterance.endTime < fromTime) continue;
      const assignment = this.assignmentFor(utterance.beginTime, utterance.endTime);
      if (assignment.speakerId === utterance.speakerId &&
        sameStrings(assignment.secondarySpeakerIds, utterance.secondarySpeakerIds)) continue;
      utterance.speakerId = assignment.speakerId;
      utterance.secondarySpeakerIds = assignment.secondarySpeakerIds;
      utterance.revision += 1;
      updates.push({
        utteranceId: utterance.utteranceId,
        revision: utterance.revision,
        speakerId: utterance.speakerId,
        secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
        beginTime: utterance.beginTime,
        endTime: utterance.endTime,
        confidence: assignment.confidence,
      });
    }
    return updates;
  }

  applyEvidenceRemap(remap: Record<string, string>, fromTime: number = 0,
    confidences: Record<string, number> = {}): DiarizationTranscriptUpdate[] {
    for (let index = 0; index < this.turns.length; index++) {
      const turn = this.turns[index];
      if (turn.endTime < fromTime) continue;
      if (turn.evidenceKey !== undefined) {
        turn.speakerId = remap[turn.evidenceKey] ?? turn.speakerId;
        turn.confidence = confidences[turn.evidenceKey] ?? turn.confidence;
      }
      const evidenceKeys = turn.secondaryEvidenceKeys ?? [];
      turn.secondaryEvidenceSpeakerIds = (turn.secondaryEvidenceSpeakerIds ?? turn.secondarySpeakerIds)
        .map((speakerId: string, secondaryIndex: number): string =>
          remap[evidenceKeys[secondaryIndex]] ?? speakerId);
      turn.secondarySpeakerIds = visibleSecondaryIds(turn.secondaryEvidenceSpeakerIds, turn.speakerId);
    }
    const updates: DiarizationTranscriptUpdate[] = [];
    for (let index = 0; index < this.utterances.length; index++) {
      const utterance = this.utterances[index];
      if (utterance.endTime < fromTime) continue;
      const assignment = this.assignmentFor(utterance.beginTime, utterance.endTime);
      if (assignment.speakerId === utterance.speakerId &&
        sameStrings(assignment.secondarySpeakerIds, utterance.secondarySpeakerIds)) continue;
      utterance.speakerId = assignment.speakerId;
      utterance.secondarySpeakerIds = assignment.secondarySpeakerIds;
      utterance.revision += 1;
      updates.push({
        utteranceId: utterance.utteranceId,
        revision: utterance.revision,
        speakerId: utterance.speakerId,
        secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
        beginTime: utterance.beginTime,
        endTime: utterance.endTime,
        confidence: assignment.confidence,
      });
    }
    return updates;
  }

  private intersectsAny(utterance: StoredUtterance, turns: SpeakerTimelineTurn[]): boolean {
    for (let i = 0; i < turns.length; i++) {
      if (overlapMs(utterance.beginTime, utterance.endTime,
        turns[i].beginTime, turns[i].endTime) > 0) return true;
    }
    return false;
  }

  private assignmentFor(beginTime: number, endTime: number): {
    speakerId: string;
    secondarySpeakerIds: string[];
    confidence: number;
  } {
    const durations = new Map<string, number>();
    const secondary = new Set<string>();
    let coveredMs = 0;
    for (let i = 0; i < this.turns.length; i++) {
      const turn = this.turns[i];
      const duration = overlapMs(beginTime, endTime, turn.beginTime, turn.endTime);
      if (duration <= 0) continue;
      durations.set(turn.speakerId, (durations.get(turn.speakerId) ?? 0) + duration);
      coveredMs += duration;
      for (let j = 0; j < turn.secondarySpeakerIds.length; j++) {
        secondary.add(turn.secondarySpeakerIds[j]);
      }
    }
    let speakerId = UNKNOWN_SPEAKER;
    let bestDuration = 0;
    durations.forEach((duration: number, candidate: string): void => {
      if (duration > bestDuration) {
        bestDuration = duration;
        speakerId = candidate;
      }
    });
    secondary.delete(speakerId);
    return {
      speakerId,
      secondarySpeakerIds: Array.from(secondary).sort(),
      confidence: coveredMs <= 0 ? 0 : Math.min(1, bestDuration / coveredMs),
    };
  }

  private turnAt(timeMs: number): SpeakerTimelineTurn | undefined {
    for (let i = this.turns.length - 1; i >= 0; i--) {
      if (timeMs >= this.turns[i].beginTime && timeMs < this.turns[i].endTime) {
        return this.turns[i];
      }
    }
    return undefined;
  }

  private splitByTokenSpeaker(utterance: StoredUtterance,
    textBoundaries: number[]): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    const unanimous = this.unanimousSpeakerTurn(utterance);
    let groupStart = 0;
    let active = this.turnAt(utterance.tokenTimesMs[0]) ?? unanimous;
    for (let index = 1; index <= utterance.tokens.length; index++) {
      const next = index < utterance.tokens.length ?
        (this.turnAt(utterance.tokenTimesMs[index]) ?? unanimous) : undefined;
      const same = index < utterance.tokens.length &&
        (next?.speakerId ?? UNKNOWN_SPEAKER) === (active?.speakerId ?? UNKNOWN_SPEAKER);
      if (same) continue;
      const beginTime = groupStart === 0 ? utterance.beginTime : utterance.tokenTimesMs[groupStart];
      const endTime = index < utterance.tokens.length ?
        utterance.tokenTimesMs[index] : utterance.endTime;
      // Secondary/overlap changes annotate speech; they are not primary speaker
      // boundaries. Keep the exact intervals in allTurns() and summarize every
      // overlapping interval here, including those between token timestamps.
      const secondarySpeakerIds = new Set<string>(active?.secondarySpeakerIds ?? []);
      let overlap = active?.overlap ?? secondarySpeakerIds.size > 0;
      for (const turn of this.turns) {
        if (overlapMs(beginTime, endTime, turn.beginTime, turn.endTime) <= 0) continue;
        for (const id of turn.secondarySpeakerIds) {
          if (id !== (active?.speakerId ?? UNKNOWN_SPEAKER)) secondarySpeakerIds.add(id);
        }
        overlap = overlap || (turn.overlap ?? turn.secondarySpeakerIds.length > 0);
      }
      result.push({
        utteranceId: result.length === 0 ? utterance.utteranceId :
          `${utterance.utteranceId}.${result.length + 1}`,
        sourceUtteranceId: utterance.utteranceId,
        rawText: utterance.tokens.slice(groupStart, index).join(''),
        text: utterance.text.slice(textBoundaries[groupStart], textBoundaries[index]),
        beginTime,
        endTime,
        speakerId: active?.speakerId ?? UNKNOWN_SPEAKER,
        secondarySpeakerIds: Array.from(secondarySpeakerIds),
        confidence: active?.confidence ?? 0,
        overlap,
      });
      groupStart = index;
      active = next;
    }
    return this.backfillUnknown(result);
  }

  private backfillUnknown(parts: DiarizedTranscriptUtterance[]): DiarizedTranscriptUtterance[] {
    const resolved = parts.map((part, index): DiarizedTranscriptUtterance => {
      const duration = part.endTime - part.beginTime;
      if (part.speakerId !== UNKNOWN_SPEAKER || duration <= 0 || duration > MAX_UNKNOWN_BACKFILL_MS ||
        part.overlap || part.secondarySpeakerIds.length > 0) return part;
      const previous = index > 0 ? parts[index - 1] : undefined;
      const next = index + 1 < parts.length ? parts[index + 1] : undefined;
      if (previous !== undefined && next !== undefined && previous.speakerId !== next.speakerId) return part;
      if ([previous, next].some(neighbour => neighbour !== undefined &&
        (neighbour.overlap || neighbour.secondarySpeakerIds.length > 0))) return part;
      const speakerId = previous?.speakerId ?? next?.speakerId;
      if (speakerId === undefined || speakerId === UNKNOWN_SPEAKER) return part;
      // Preserve real short turns even when no token timestamp landed in them.
      if (this.turns.some(turn => turn.speakerId !== UNKNOWN_SPEAKER && turn.speakerId !== speakerId &&
        overlapMs(part.beginTime, part.endTime, turn.beginTime, turn.endTime) > 0)) return part;
      return { ...part, speakerId, confidence: 0, speakerInferred: true };
    });
    const merged: DiarizedTranscriptUtterance[] = [];
    for (const part of resolved) {
      const previous = merged[merged.length - 1];
      if (previous !== undefined && previous.speakerId === part.speakerId) {
        previous.rawText += part.rawText;
        previous.text += part.text;
        previous.endTime = part.endTime;
        previous.confidence = Math.min(previous.confidence ?? 0, part.confidence ?? 0);
        previous.speakerInferred = previous.speakerInferred || part.speakerInferred;
        previous.overlap = previous.overlap || part.overlap;
        previous.secondarySpeakerIds = Array.from(new Set([...previous.secondarySpeakerIds,
          ...part.secondarySpeakerIds]));
      } else {
        merged.push({ ...part, secondarySpeakerIds: part.secondarySpeakerIds.slice(),
          utteranceId: merged.length === 0 ? part.sourceUtteranceId :
            `${part.sourceUtteranceId}.${merged.length + 1}` });
      }
    }
    return merged;
  }

  private unanimousSpeakerTurn(utterance: StoredUtterance): SpeakerTimelineTurn | undefined {
    let candidate: SpeakerTimelineTurn | undefined;
    for (const turn of this.turns) {
      if (overlapMs(utterance.beginTime, utterance.endTime, turn.beginTime, turn.endTime) <= 0) continue;
      // Missing acoustic coverage is distinct from an explicitly uncertain or overlapping turn.
      if (turn.speakerId === UNKNOWN_SPEAKER || turn.overlap || turn.secondarySpeakerIds.length > 0 ||
        (candidate !== undefined && candidate.speakerId !== turn.speakerId)) return undefined;
      candidate = turn;
    }
    return candidate;
  }

  private unsplitUtterance(utterance: StoredUtterance): DiarizedTranscriptUtterance {
    const assignment = this.assignmentFor(utterance.beginTime, utterance.endTime);
    return {
      utteranceId: utterance.utteranceId,
      sourceUtteranceId: utterance.utteranceId,
      rawText: utterance.rawText,
      text: utterance.text,
      beginTime: utterance.beginTime,
      endTime: utterance.endTime,
      speakerId: utterance.speakerId,
      secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
      confidence: assignment.confidence,
      overlap: this.hasOverlap(utterance.beginTime, utterance.endTime),
    };
  }

  private hasOverlap(beginTime: number, endTime: number): boolean {
    for (let index = 0; index < this.turns.length; index++) {
      const turn = this.turns[index];
      if ((turn.overlap ?? turn.secondarySpeakerIds.length > 0) &&
        overlapMs(beginTime, endTime, turn.beginTime, turn.endTime) > 0) return true;
    }
    return false;
  }
}
