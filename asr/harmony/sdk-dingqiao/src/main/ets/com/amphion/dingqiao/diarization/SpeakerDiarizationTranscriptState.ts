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

// Exact alignment handles inserted punctuation/spacing. Lexical rewrites fall
// back to the conservative partial-alignment path below.
function tokenTextBoundaries(tokens: string[], text: string): number[] | undefined {
  const inserted = ' ,.!?，。！？、;；:：\t\r\n';
  const boundaries: number[] = [0];
  let cursor = 0;
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.length === 0) return undefined;
    for (let character = 0; character < token.length; character++) {
      const beforeInserted = cursor;
      while (cursor < text.length && text[cursor] !== token[character] &&
        inserted.indexOf(text[cursor]) >= 0) cursor++;
      const matches = cursor < text.length && text[cursor] === token[character];
      // Punctuation can replace a word separator. Keep its timestamp boundary
      // without treating the following lexical character as that separator.
      // A sliced clause can also start with the replaced separator.
      const replacedSpace = !matches && ' \t\r\n'.indexOf(token[character]) >= 0 &&
        (cursor === 0 || /[,.!?，。！？、;；:：]/.test(text.slice(beforeInserted, cursor)));
      if (!matches && !replacedSpace) return undefined;
      // Keep inserted sentence punctuation with the preceding token.
      if (index > 0 && character === 0) boundaries.push(cursor);
      if (matches) cursor++;
    }
  }
  while (cursor < text.length && inserted.indexOf(text[cursor]) >= 0) cursor++;
  if (cursor !== text.length) return undefined;
  boundaries.push(cursor);
  return boundaries;
}

interface TranscriptCut {
  tokenIndex: number;
  textOffset: number;
}

// A lexical rewrite must not invalidate unrelated clauses. Retain only cuts
// shared by every minimum-edit path; repeated/deleted text cannot choose a
// convenient occurrence. Rewritten pieces still use the conservative fallback.
function unambiguousPunctuationCuts(tokens: string[], text: string): TranscriptCut[] {
  const original = tokens.join('');
  const inserted = ' ,.!?，。！？、;；:：\t\r\n';
  const raw = Array.from(original);
  const plain: string[] = [];
  const textOffsets: number[] = [];
  let offset = 0;
  for (const character of Array.from(text)) {
    if (inserted.indexOf(character) < 0) {
      plain.push(character);
      textOffsets.push(offset);
    }
    offset += character.length;
  }
  const fallback = [{ tokenIndex: 0, textOffset: 0 },
    { tokenIndex: tokens.length, textOffset: text.length }];
  // Two uint32 matrices use at most 8 MiB. Long or already-punctuated raw
  // endpoints keep the existing unsplit result instead of allocating unboundedly.
  const width = plain.length + 1;
  const cells = (raw.length + 1) * width;
  if (raw.length === 0 || plain.length === 0 || cells > 1_048_576 ||
    raw.some(character => inserted.indexOf(character) >= 0)) return fallback;
  const forward = new Uint32Array(cells);
  const backward = new Uint32Array(cells);
  for (let i = 0; i <= raw.length; i++) forward[i * width] = i;
  for (let j = 0; j <= plain.length; j++) forward[j] = j;
  for (let i = 1; i <= raw.length; i++) {
    for (let j = 1; j <= plain.length; j++) {
      forward[i * width + j] = Math.min(forward[(i - 1) * width + j] + 1,
        forward[i * width + j - 1] + 1,
        forward[(i - 1) * width + j - 1] + (raw[i - 1] === plain[j - 1] ? 0 : 1));
    }
  }
  for (let i = 0; i <= raw.length; i++) backward[i * width + plain.length] = raw.length - i;
  for (let j = 0; j <= plain.length; j++) backward[raw.length * width + j] = plain.length - j;
  for (let i = raw.length - 1; i >= 0; i--) {
    for (let j = plain.length - 1; j >= 0; j--) {
      backward[i * width + j] = Math.min(backward[(i + 1) * width + j] + 1,
        backward[i * width + j + 1] + 1,
        backward[(i + 1) * width + j + 1] + (raw[i] === plain[j] ? 0 : 1));
    }
  }
  const cost = forward[cells - 1];
  const owners: number[] = [];
  for (let j = 0; j < plain.length; j++) {
    let owner = -1;
    let ambiguous = false;
    for (let i = 0; i <= raw.length; i++) {
      const prefix = forward[i * width + j];
      if (prefix + 1 + backward[i * width + j + 1] === cost) ambiguous = true;
      if (i === raw.length) continue;
      const exact = raw[i] === plain[j];
      if (prefix + (exact ? 0 : 1) + backward[(i + 1) * width + j + 1] === cost) {
        if (!exact || (owner >= 0 && owner !== i)) ambiguous = true;
        owner = i;
      }
    }
    owners.push(ambiguous ? -1 : owner);
  }
  const tokenAt: Map<number, number> = new Map<number, number>();
  let characters = 0;
  for (let index = 0; index < tokens.length; index++) {
    tokenAt.set(characters, index);
    characters += Array.from(tokens[index]).length;
  }
  const cuts: TranscriptCut[] = [fallback[0]];
  for (let j = 1; j < plain.length; j++) {
    const gap = text.slice(textOffsets[j - 1] + plain[j - 1].length, textOffsets[j]);
    const tokenIndex = tokenAt.get(owners[j]);
    if (/[，。！？；]/.test(gap) && owners[j - 1] >= 0 && owners[j] === owners[j - 1] + 1 &&
      tokenIndex !== undefined && tokenIndex > 0) {
      cuts.push({ tokenIndex, textOffset: textOffsets[j] });
    }
  }
  cuts.push(fallback[1]);
  return cuts;
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

  // Internal alignment evidence for the existing bounded UNKNOWN backfill.
  // Public output uses sentenceUtterances; these pieces are never published.
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

  private punctuationUnits(utterance: StoredUtterance): StoredUtterance[] {
    if (utterance.tokens.length === 0 || utterance.tokens.length !== utterance.tokenTimesMs.length ||
      utterance.tokens.join('') !== utterance.rawText) return [utterance];
    const boundaries = tokenTextBoundaries(utterance.tokens, utterance.text);
    let cuts: TranscriptCut[];
    if (boundaries === undefined) {
      cuts = unambiguousPunctuationCuts(utterance.tokens, utterance.text);
    } else {
      cuts = [{ tokenIndex: 0, textOffset: 0 }];
      for (let index = 1; index < utterance.tokens.length; index++) {
        if (/[，。！？；]\s*$/.test(utterance.text.slice(boundaries[index - 1], boundaries[index]))) {
          if (boundaries[index] < utterance.text.length) {
            cuts.push({ tokenIndex: index, textOffset: boundaries[index] });
          }
        }
      }
      cuts.push({ tokenIndex: utterance.tokens.length, textOffset: utterance.text.length });
    }
    if (cuts.length === 2) return [utterance];
    return cuts.slice(0, -1).map((cut, index) => {
      const start = cut.tokenIndex;
      const end = cuts[index + 1].tokenIndex;
      return { ...utterance, utteranceId: index === 0 ? utterance.utteranceId : `${utterance.utteranceId}.${index + 1}`,
        text: utterance.text.slice(cut.textOffset, cuts[index + 1].textOffset),
        rawText: utterance.tokens.slice(start, end).join(''), tokens: utterance.tokens.slice(start, end),
        tokenTimesMs: utterance.tokenTimesMs.slice(start, end),
        beginTime: start === 0 ? utterance.beginTime : utterance.tokenTimesMs[start],
        endTime: end === utterance.tokens.length ? utterance.endTime : utterance.tokenTimesMs[end] };
    });
  }

  sentenceUtterances(throughTime: number = Number.POSITIVE_INFINITY): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    for (const original of this.utterances.filter(utterance => (utterance.audioEndTime ?? utterance.endTime) <= throughTime)) {
      const units = this.punctuationUnits(original).map(utterance => {
        const boundaries = utterance.tokens.length > 0 && utterance.tokens.length === utterance.tokenTimesMs.length ?
          tokenTextBoundaries(utterance.tokens, utterance.text) : undefined;
        const parts = boundaries === undefined ? [this.unsplitUtterance(utterance)] : this.splitByTokenSpeaker(utterance, boundaries);
        const turns = this.turns.filter(turn =>
          overlapMs(utterance.beginTime, utterance.endTime, turn.beginTime, turn.endTime) > 0);
        const participants = new Set<string>();
        for (const turn of turns) {
          participants.add(turn.speakerId);
          for (const id of turn.secondarySpeakerIds) participants.add(id);
        }
        const known = Array.from(participants).filter(id => id !== UNKNOWN_SPEAKER && id !== 'UNKNOWN_SECONDARY');
        const overlap = turns.some(turn => turn.overlap || turn.secondarySpeakerIds.length > 0);
        // Check actual acoustic UNKNOWN spans too: token timestamps may skip one.
        const unknown = this.turns.filter(turn =>
          overlapMs(original.beginTime, original.endTime, turn.beginTime, turn.endTime) > 0).filter(turn => turn.speakerId === UNKNOWN_SPEAKER)
          .sort((a, b) => a.beginTime - b.beginTime);
        let unknownBegin = -1;
        let unknownEnd = -1;
        let bounded = true;
        for (const turn of unknown) {
          const begin = Math.max(original.beginTime, turn.beginTime);
          const end = Math.min(original.endTime, turn.endTime);
          if (begin > unknownEnd) unknownBegin = begin;
          unknownEnd = Math.max(unknownEnd, end);
          if (unknownEnd - unknownBegin > MAX_UNKNOWN_BACKFILL_MS &&
            overlapMs(utterance.beginTime, utterance.endTime, unknownBegin, unknownEnd) > 0) bounded = false;
        }
        const single = known.length === 1 && !overlap && bounded && parts.length > 0 &&
          parts.every(part => part.speakerId === known[0]);
        const inferred = single && (turns.some(turn => turn.speakerId === UNKNOWN_SPEAKER) || parts.some(part => part.speakerInferred));
        return {
          utteranceId: utterance.utteranceId,
          sourceUtteranceId: original.utteranceId,
          rawText: utterance.rawText,
          text: utterance.text,
          beginTime: utterance.beginTime,
          endTime: utterance.endTime,
          speakerId: single ? known[0] : UNKNOWN_SPEAKER,
          secondarySpeakerIds: single ? [] : Array.from(participants).sort(),
          confidence: single && !inferred ? Math.min(...parts.map(part => part.confidence ?? 0)) : 0,
          overlap,
          speakerInferred: inferred,
        };
      });
      for (const part of units) {
        const previous = result[result.length - 1];
        if (previous !== undefined && previous.sourceUtteranceId === part.sourceUtteranceId &&
          previous.endTime === part.beginTime && previous.speakerId === part.speakerId &&
          previous.overlap === part.overlap && sameStrings(previous.secondarySpeakerIds, part.secondarySpeakerIds)) {
          previous.text += part.text;
          previous.rawText += part.rawText;
          previous.endTime = part.endTime;
          previous.confidence = Math.min(previous.confidence ?? 0, part.confidence ?? 0);
          previous.speakerInferred = previous.speakerInferred || part.speakerInferred;
        } else {
          result.push(part);
        }
      }
    }
    return result;
  }

  commitThrough(endTime: number): DiarizedTranscriptUtterance[] {
    const result = this.sentenceUtterances(endTime);
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

  resolveUnknownSpan(evidenceKey: string, beginTime: number, endTime: number, speakerId: string,
    confidence: number, remap: Record<string, string>): void {
    if (endTime <= beginTime) return;
    const revised: SpeakerTimelineTurn[] = [];
    for (const turn of this.turns) {
      if (turn.evidenceKey !== evidenceKey || (remap[evidenceKey] ?? turn.speakerId) !== UNKNOWN_SPEAKER ||
        turn.overlap || (turn.secondaryEvidenceSpeakerIds ?? turn.secondarySpeakerIds).length > 0 ||
        overlapMs(beginTime, endTime, turn.beginTime, turn.endTime) <= 0) {
        revised.push(turn);
        continue;
      }
      const start = Math.max(beginTime, turn.beginTime);
      const end = Math.min(endTime, turn.endTime);
      if (turn.beginTime < start) revised.push({ ...turn, endTime: start });
      revised.push({ ...turn, beginTime: start, endTime: end, speakerId, confidence, evidenceKey: undefined });
      if (end < turn.endTime) revised.push({ ...turn, beginTime: end });
    }
    this.turns.splice(0, this.turns.length, ...revised);
  }

  // Used only at commit, after identity resolution and before the final remap.
  // A new native boundary may split a mistaken single identity; it must not erase
  // UNKNOWN, overlap, or even a brief already-distinct known speaker.
  refineSingleSpeakerSpan(beginTime: number, cutTime: number, endTime: number,
    leftId: string, rightId: string, leftConfidence: number, rightConfidence: number,
    remap: Record<string, string>): void {
    if (cutTime <= beginTime || cutTime >= endTime || leftId === rightId) return;
    const covered = this.turns.filter(turn => overlapMs(beginTime, endTime, turn.beginTime, turn.endTime) > 0);
    const ids = new Set(covered.map(turn => remap[turn.evidenceKey ?? ''] ?? turn.speakerId));
    if (ids.size !== 1 || (!ids.has(leftId) && !ids.has(rightId)) || ids.has(UNKNOWN_SPEAKER) ||
      covered.some(turn => turn.overlap || (turn.secondaryEvidenceSpeakerIds ?? turn.secondarySpeakerIds).length > 0)) return;
    const revised: SpeakerTimelineTurn[] = [];
    for (const turn of this.turns) {
      const cuts = [turn.beginTime, ...[beginTime, cutTime, endTime].filter(time =>
        time > turn.beginTime && time < turn.endTime), turn.endTime].sort((a, b) => a - b);
      for (let index = 1; index < cuts.length; index++) {
        const start = cuts[index - 1];
        const end = cuts[index];
        const part: SpeakerTimelineTurn = { ...turn, beginTime: start, endTime: end };
        if (start >= beginTime && end <= endTime) {
          part.speakerId = start < cutTime ? leftId : rightId;
          part.confidence = start < cutTime ? leftConfidence : rightConfidence;
          // This committed child is supported by its own PCM, not the old parent.
          part.evidenceKey = undefined;
        }
        revised.push(part);
      }
    }
    this.turns.splice(0, this.turns.length, ...revised);
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
    const participants = new Set<string>();
    let overlap = false;
    let confidence = 1;
    for (let i = 0; i < this.turns.length; i++) {
      const turn = this.turns[i];
      const duration = overlapMs(beginTime, endTime, turn.beginTime, turn.endTime);
      if (duration <= 0) continue;
      participants.add(turn.speakerId);
      overlap = overlap || !!turn.overlap || turn.secondarySpeakerIds.length > 0;
      confidence = Math.min(confidence, turn.confidence ?? 0);
      for (let j = 0; j < turn.secondarySpeakerIds.length; j++) {
        participants.add(turn.secondarySpeakerIds[j]);
      }
    }
    const single = participants.size === 1 && !participants.has(UNKNOWN_SPEAKER) &&
      !participants.has('UNKNOWN_SECONDARY') && !overlap;
    const speakerId = single ? Array.from(participants)[0] : UNKNOWN_SPEAKER;
    return {
      speakerId,
      secondarySpeakerIds: single ? [] : Array.from(participants).sort(),
      confidence: single ? confidence : 0,
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
          if (id !== (active?.speakerId ?? UNKNOWN_SPEAKER) ||
            (active?.speakerId ?? UNKNOWN_SPEAKER) === UNKNOWN_SPEAKER) secondarySpeakerIds.add(id);
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
      if (part.speakerId !== UNKNOWN_SPEAKER || duration < 0 || duration > MAX_UNKNOWN_BACKFILL_MS ||
        this.blocksBackfill(part)) return part;
      const previous = index > 0 ? parts[index - 1] : undefined;
      const next = index + 1 < parts.length ? parts[index + 1] : undefined;
      if (previous !== undefined && next !== undefined && previous.speakerId !== next.speakerId) return part;
      if ([previous, next].some(neighbour => neighbour !== undefined &&
        this.blocksBackfill(neighbour))) return part;
      const speakerId = previous?.speakerId ?? next?.speakerId;
      if (speakerId === undefined || speakerId === UNKNOWN_SPEAKER) return part;
      let evidenceBegin = part.beginTime;
      if (duration === 0) {
        // The last token's start can equal the public end timestamp. It has no
        // interval of its own; require recent acoustic support, not just an old
        // paragraph label, before keeping this terminal text with its neighbour.
        if (next !== undefined || previous === undefined || previous.endTime !== part.beginTime) return part;
        evidenceBegin = Math.max(previous.beginTime, part.beginTime - MAX_UNKNOWN_BACKFILL_MS);
        if (!this.turns.some(turn => turn.speakerId === speakerId &&
          overlapMs(evidenceBegin, part.endTime, turn.beginTime, turn.endTime) > 0)) return part;
      }
      // Preserve real short turns even when no token timestamp landed in them.
      if (this.turns.some(turn => overlapMs(evidenceBegin, part.endTime, turn.beginTime, turn.endTime) > 0 &&
        ((turn.speakerId !== UNKNOWN_SPEAKER && turn.speakerId !== speakerId) ||
          this.blocksBackfill(turn)))) return part;
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

  private blocksBackfill(part: SpeakerTimelineTurn): boolean {
    // An unidentified secondary voice does not establish a different primary
    // identity. Preserve that uncertainty in the merged text and raw timeline.
    return part.secondarySpeakerIds.some(id => id !== 'UNKNOWN' && id !== 'UNKNOWN_SECONDARY') ||
      ((part.overlap ?? false) && part.secondarySpeakerIds.length === 0);
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
