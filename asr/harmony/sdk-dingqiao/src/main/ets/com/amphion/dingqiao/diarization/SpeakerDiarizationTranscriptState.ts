export interface DiarizationTranscriptInput {
  rawText: string;
  text: string;
  tokens: string[];
  tokenTimesMs: number[];
  beginTime: number;
  endTime: number;
  audioEndTime?: number;
  textNormalization?: TranscriptTextNormalization;
  presentation?: TranscriptTextPresentation;
}

export interface TranscriptNormalizationSpan {
  sourceBegin: number;
  sourceEnd: number;
  textBegin: number;
  textEnd: number;
}

export interface TranscriptTextNormalization {
  text: string;
  spans: TranscriptNormalizationSpan[];
}

// Records from a later postprocessor that rewrites the final text without an
// internal offset map: spans map clauses of sourceText (its input) to `text`.
export interface TranscriptTextPresentation {
  sourceText: string;
  spans: TranscriptNormalizationSpan[];
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
  speakerTextSpans?: DiarizedTranscriptTextSpan[];
}

// UTF-16 offsets into the containing item's rawText and text. These describe
// text ownership, not replacement acoustic intervals or paragraph boundaries.
export interface DiarizedTranscriptTextSpan {
  sourceBegin: number;
  sourceEnd: number;
  textBegin: number;
  textEnd: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  confidence: number;
  overlap: boolean;
  speakerInferred: boolean;
}

interface StoredUtterance extends DiarizationTranscriptInput {
  utteranceId: string;
  revision: number;
  speakerId: string;
  secondarySpeakerIds: string[];
}

const UNKNOWN_SPEAKER = 'UNKNOWN';
// Fixed authorized inference bound (not the model hop). See delivery/harmony-dingqiao/docs/UNKNOWN_SPEAKER_BACKFILL.md for the
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

function isAsciiAt(text: string, index: number): boolean {
  return index >= 0 && index < text.length && text.charCodeAt(index) < 0x80;
}

// Exact alignment handles inserted punctuation/spacing. Lexical rewrites
// require provenance from the postprocessor; edit distance is not provenance.
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
      // A sliced clause can also start with the replaced separator. sherpa's
      // CT punctuation rejoins words with a space only between two ASCII
      // characters, so it drops every other separator; joined ASCII words stay unaligned.
      const replacedSpace = !matches && ' \t\r\n'.indexOf(token[character]) >= 0 &&
        (cursor === 0 || /[,.!?，。！？、;；:：]/.test(text.slice(beforeInserted, cursor)) ||
          !(isAsciiAt(text, cursor - 1) && isAsciiAt(text, cursor)));
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

interface TranscriptPresentationAlignment {
  sourceOffsets: number[];
  textOffsets: number[];
}

// Maps an alignment against a postprocessor's input onto its published text.
// An unchanged record maps character for character; a rewritten record has no
// internal offsets, so boundaries inside it are dropped and it stays indivisible.
// Text inserted at a boundary stays with the preceding unit, like inserted
// punctuation; a boundary that would leave an empty unit is dropped.
function presentedAlignment(alignment: TranscriptPresentationAlignment,
  presentation: TranscriptTextPresentation, text: string): TranscriptPresentationAlignment | undefined {
  const spans = presentation.spans;
  let sourceEnd = 0;
  let textEnd = 0;
  for (const span of spans) {
    if (![span.sourceBegin, span.sourceEnd, span.textBegin, span.textEnd].every(value => Number.isInteger(value)) ||
      span.sourceBegin !== sourceEnd || span.textBegin !== textEnd ||
      span.sourceEnd < span.sourceBegin || span.textEnd < span.textBegin) return undefined;
    sourceEnd = span.sourceEnd;
    textEnd = span.textEnd;
  }
  if (spans.length === 0 || sourceEnd !== presentation.sourceText.length || textEnd !== text.length) return undefined;
  const sourceOffsets = [0];
  const textOffsets = [0];
  let record = 0;
  const last = alignment.textOffsets.length - 1;
  for (let index = 1; index < last; index++) {
    const offset = alignment.textOffsets[index];
    while (spans[record].sourceEnd < offset) record++;
    let mapped = -1;
    if (spans[record].sourceEnd === offset) {
      let end = record;
      while (end + 1 < spans.length && spans[end + 1].sourceBegin === offset &&
        spans[end + 1].sourceEnd === offset) end++;
      mapped = spans[end].textEnd;
    } else if (presentation.sourceText.slice(spans[record].sourceBegin, spans[record].sourceEnd) ===
      text.slice(spans[record].textBegin, spans[record].textEnd)) {
      mapped = spans[record].textBegin + offset - spans[record].sourceBegin;
    }
    if (mapped <= textOffsets[textOffsets.length - 1] || mapped >= text.length) continue;
    sourceOffsets.push(alignment.sourceOffsets[index]);
    textOffsets.push(mapped);
  }
  sourceOffsets.push(alignment.sourceOffsets[last]);
  textOffsets.push(text.length);
  return { sourceOffsets, textOffsets };
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
  // Audio after this point was never inferred (finish-timeout salvage). Its lack of
  // turns is not evidence of silence, so UNKNOWN text there is not backfilled.
  private evidenceEndTime: number = Number.POSITIVE_INFINITY;

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
      textNormalization: input.textNormalization === undefined ? undefined : {
        text: input.textNormalization.text,
        spans: input.textNormalization.spans.map(span => ({ ...span })),
      },
      presentation: input.presentation === undefined ? undefined : {
        sourceText: input.presentation.sourceText,
        spans: input.presentation.spans.map(span => ({ ...span })),
      },
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

  limitEvidence(endTime: number): void { this.evidenceEndTime = Math.min(this.evidenceEndTime, endTime); }

  applySpeakerTurns(newTurns: SpeakerTimelineTurn[], replace: boolean = false): DiarizationTranscriptUpdate[] {
    // Community previews are complete snapshots of the uncommitted range.
    // A correction to silence/UNKNOWN must also remove earlier provisional turns.
    if (replace) this.turns.splice(0, this.turns.length);
    if (newTurns.length === 0 && !replace) return [];
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
      if (!replace && !this.intersectsAny(utterance, newTurns)) continue;
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

  private sourceAssignments(utterance: StoredUtterance): DiarizedTranscriptUtterance[] {
    const source: StoredUtterance = { ...utterance, text: utterance.rawText };
    const boundaries = source.tokens.length > 0 && source.tokens.length === source.tokenTimesMs.length &&
      source.tokens.join('') === source.rawText ? tokenTextBoundaries(source.tokens, source.rawText) : undefined;
    return boundaries === undefined ? [this.unsplitUtterance(source)] :
      this.splitByTokenSpeaker(source, boundaries, false);
  }

  private punctuationUnits(utterance: StoredUtterance): StoredUtterance[] {
    if (utterance.tokens.length === 0 || utterance.tokens.length !== utterance.tokenTimesMs.length ||
      utterance.tokens.join('') !== utterance.rawText) return [utterance];
    const alignment = this.presentationAlignment(utterance);
    let cuts: TranscriptCut[];
    if (alignment === undefined) {
      return [utterance];
    } else {
      const tokenOffsets = [0];
      for (const token of utterance.tokens) tokenOffsets.push(tokenOffsets[tokenOffsets.length - 1] + token.length);
      cuts = [{ tokenIndex: 0, textOffset: 0 }];
      for (let index = 1; index < alignment.sourceOffsets.length - 1; index++) {
        const tokenIndex = tokenOffsets.indexOf(alignment.sourceOffsets[index]);
        if (tokenIndex <= 0) continue;
        if (/[，。！？；]\s*$/.test(utterance.text.slice(alignment.textOffsets[index - 1], alignment.textOffsets[index]))) {
          if (alignment.textOffsets[index] < utterance.text.length) {
            cuts.push({ tokenIndex, textOffset: alignment.textOffsets[index] });
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

  private presentationAlignment(utterance: StoredUtterance): TranscriptPresentationAlignment | undefined {
    const direct = this.alignmentTo(utterance, utterance.text);
    if (direct !== undefined || utterance.presentation === undefined) return direct;
    const source = this.alignmentTo(utterance, utterance.presentation.sourceText);
    return source === undefined ? undefined : presentedAlignment(source, utterance.presentation, utterance.text);
  }

  private alignmentTo(utterance: StoredUtterance, text: string): TranscriptPresentationAlignment | undefined {
    if (utterance.tokens.length === 0 || utterance.tokens.length !== utterance.tokenTimesMs.length ||
      utterance.tokens.join('') !== utterance.rawText) return undefined;
    const exact = tokenTextBoundaries(utterance.tokens, text);
    if (exact !== undefined) {
      const sourceOffsets = [0];
      for (const token of utterance.tokens) sourceOffsets.push(sourceOffsets[sourceOffsets.length - 1] + token.length);
      return { sourceOffsets, textOffsets: exact };
    }
    const normalization = utterance.textNormalization;
    if (normalization === undefined || normalization.spans.length === 0) return undefined;
    const sourceOffsets = [0];
    const pieces: string[] = [];
    let textEnd = 0;
    for (const span of normalization.spans) {
      if (![span.sourceBegin, span.sourceEnd, span.textBegin, span.textEnd].every(value => Number.isInteger(value)) ||
        span.sourceBegin !== sourceOffsets[sourceOffsets.length - 1] || span.textBegin !== textEnd ||
        span.sourceEnd <= span.sourceBegin || span.sourceEnd > utterance.rawText.length ||
        span.textEnd <= span.textBegin || span.textEnd > normalization.text.length) return undefined;
      // Offsets must be complete Unicode boundaries, not the middle of a pair.
      if ([utterance.rawText.charCodeAt(span.sourceEnd), normalization.text.charCodeAt(span.textEnd)]
        .some(value => value >= 0xDC00 && value <= 0xDFFF)) return undefined;
      sourceOffsets.push(span.sourceEnd);
      pieces.push(normalization.text.slice(span.textBegin, span.textEnd));
      textEnd = span.textEnd;
    }
    if (sourceOffsets[sourceOffsets.length - 1] !== utterance.rawText.length ||
      textEnd !== normalization.text.length) return undefined;
    const textOffsets = tokenTextBoundaries(pieces, text);
    return textOffsets === undefined ? undefined : { sourceOffsets, textOffsets };
  }

  sentenceUtterances(throughTime: number = Number.POSITIVE_INFINITY): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    for (const original of this.utterances.filter(utterance => (utterance.audioEndTime ?? utterance.endTime) <= throughTime)) {
      // Associate and infer once within the native utterance. Presentation cuts
      // may select existing assignments, but must never rerun neighbour inference.
      const alignment = this.presentationAlignment(original);
      const source = this.sourceAssignments(original);
      const aligned = alignment === undefined ? [this.unsplitUtterance(original)] : source;
      const textSpans = alignment === undefined ? [] : this.alignedTextSpans(original, source, alignment);
      let sourceOffset = 0;
      let textOffset = 0;
      const units = this.punctuationUnits(original).map(utterance => {
        const sourceBegin = sourceOffset;
        const textBegin = textOffset;
        sourceOffset += utterance.rawText.length;
        textOffset += utterance.text.length;
        const speakerTextSpans = textSpans.filter(span =>
          span.sourceBegin >= sourceBegin && span.sourceEnd <= sourceOffset).map(span => ({
            ...span, sourceBegin: span.sourceBegin - sourceBegin, sourceEnd: span.sourceEnd - sourceBegin,
            textBegin: span.textBegin - textBegin, textEnd: span.textEnd - textBegin,
            secondarySpeakerIds: span.secondarySpeakerIds.slice(),
          }));
        let partOffset = 0;
        const parts = aligned.filter(part => {
          const partBegin = partOffset;
          partOffset += part.rawText.length;
          return partBegin < sourceOffset && partOffset > sourceBegin;
        });
        const turns = this.turns.filter(turn =>
          overlapMs(utterance.beginTime, utterance.endTime, turn.beginTime, turn.endTime) > 0);
        const participants = new Set<string>();
        for (const turn of turns) {
          participants.add(turn.speakerId);
          for (const id of turn.secondarySpeakerIds) participants.add(id);
        }
        // An inferred tail may have no acoustic turn inside this display unit.
        // Its owner comes from the original utterance's bounded inference above.
        for (const part of parts) {
          if (part.speakerId !== UNKNOWN_SPEAKER && part.speakerId !== 'UNKNOWN_SECONDARY') {
            participants.add(part.speakerId);
          }
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
        const inferred = parts.some(part => part.speakerInferred) ||
          (single && turns.some(turn => turn.speakerId === UNKNOWN_SPEAKER));
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
          speakerTextSpans,
        };
      });
      for (const part of units) {
        const previous = result[result.length - 1];
        if (previous !== undefined && previous.sourceUtteranceId === part.sourceUtteranceId &&
          previous.endTime === part.beginTime && previous.speakerId === part.speakerId &&
          previous.overlap === part.overlap && sameStrings(previous.secondarySpeakerIds, part.secondarySpeakerIds)) {
          const sourceBegin = previous.rawText.length, textBegin = previous.text.length;
          previous.speakerTextSpans?.push(...(part.speakerTextSpans ?? []).map(span => ({
            ...span, sourceBegin: span.sourceBegin + sourceBegin, sourceEnd: span.sourceEnd + sourceBegin,
            textBegin: span.textBegin + textBegin, textEnd: span.textEnd + textBegin,
            secondarySpeakerIds: span.secondarySpeakerIds.slice(),
          })));
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
    for (const utterance of result) {
      const merged: DiarizedTranscriptTextSpan[] = [];
      for (const span of utterance.speakerTextSpans ?? []) {
        const previous = merged[merged.length - 1];
        if (previous !== undefined && previous.sourceEnd === span.sourceBegin &&
          previous.textEnd === span.textBegin && previous.speakerId === span.speakerId &&
          previous.speakerInferred === span.speakerInferred && previous.overlap === span.overlap &&
          previous.confidence === span.confidence && sameStrings(previous.secondarySpeakerIds, span.secondarySpeakerIds)) {
          previous.sourceEnd = span.sourceEnd;
          previous.textEnd = span.textEnd;
        } else merged.push(span);
      }
      utterance.speakerTextSpans = merged;
    }
    return result;
  }

  private alignedTextSpans(original: StoredUtterance, parts: DiarizedTranscriptUtterance[],
    alignment: TranscriptPresentationAlignment): DiarizedTranscriptTextSpan[] {
    const result: DiarizedTranscriptTextSpan[] = [];
    const tokenOffsets = [0];
    for (const token of original.tokens) tokenOffsets.push(tokenOffsets[tokenOffsets.length - 1] + token.length);
    for (let index = 1; index < alignment.sourceOffsets.length; index++) {
      const sourceBegin = alignment.sourceOffsets[index - 1], sourceEnd = alignment.sourceOffsets[index];
      let offset = 0;
      const owners = parts.filter(part => {
        const begin = offset;
        offset += part.rawText.length;
        return begin < sourceEnd && offset > sourceBegin;
      });
      let single = owners.length > 0 && owners.every(part => part.speakerId === owners[0].speakerId);
      // A rewritten grammar record is indivisible. Retain contrary acoustic
      // evidence even when no token start landed inside that short turn.
      const rewritten = tokenTextBoundaries([original.rawText.slice(sourceBegin, sourceEnd)],
        original.text.slice(alignment.textOffsets[index - 1], alignment.textOffsets[index])) === undefined;
      const acoustic: SpeakerTimelineTurn[] = [];
      if (rewritten) {
        const first = tokenOffsets.findIndex((offset, token) => token < original.tokens.length &&
          tokenOffsets[token + 1] > sourceBegin);
        const after = tokenOffsets.findIndex(offset => offset >= sourceEnd);
        const begin = original.tokenTimesMs[first];
        const end = original.tokenTimesMs[after] ?? original.endTime;
        acoustic.push(...this.turns.filter(turn => overlapMs(begin, end, turn.beginTime, turn.endTime) > 0));
        if (acoustic.some(turn => turn.speakerId !== UNKNOWN_SPEAKER &&
          turn.speakerId !== owners[0]?.speakerId)) single = false;
      }
      const speakerId = single ? owners[0].speakerId : UNKNOWN_SPEAKER;
      const secondary = new Set<string>();
      for (const part of owners) {
        if (part.speakerId !== speakerId) secondary.add(part.speakerId);
        for (const id of part.secondarySpeakerIds) if (id !== speakerId) secondary.add(id);
      }
      for (const turn of acoustic) {
        if (turn.speakerId !== speakerId) secondary.add(turn.speakerId);
        for (const id of turn.secondarySpeakerIds) if (id !== speakerId) secondary.add(id);
      }
      const inferred = owners.some(part => part.speakerInferred);
      result.push({ sourceBegin, sourceEnd,
        textBegin: alignment.textOffsets[index - 1], textEnd: alignment.textOffsets[index],
        speakerId, secondarySpeakerIds: Array.from(secondary).sort(),
        confidence: single && speakerId !== UNKNOWN_SPEAKER && !inferred ?
          Math.min(...owners.map(part => part.confidence ?? 0)) : 0,
        overlap: owners.some(part => part.overlap) || acoustic.some(turn => turn.overlap), speakerInferred: inferred });
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
    textBoundaries: number[], merge: boolean = true): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    let groupStart = 0;
    let active = this.turnAt(utterance.tokenTimesMs[0]);
    for (let index = 1; index <= utterance.tokens.length; index++) {
      const next = index < utterance.tokens.length ?
        this.turnAt(utterance.tokenTimesMs[index]) : undefined;
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
    return this.backfillUnknown(result, merge);
  }

  private backfillUnknown(parts: DiarizedTranscriptUtterance[], merge: boolean = true): DiarizedTranscriptUtterance[] {
    const resolved = parts.map((part, index): DiarizedTranscriptUtterance => {
      const duration = part.endTime - part.beginTime;
      if (part.speakerId !== UNKNOWN_SPEAKER || duration < 0 || duration > MAX_UNKNOWN_BACKFILL_MS ||
        part.endTime > this.evidenceEndTime || this.blocksBackfill(part)) return part;
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
    if (!merge) return resolved;
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

  private unsplitUtterance(utterance: StoredUtterance): DiarizedTranscriptUtterance {
    const assignment = this.assignmentFor(utterance.beginTime, utterance.endTime);
    // Wetext currently returns only a string. Without exact source relations,
    // lexical merges/expansions/replacements cannot acquire a guessed owner.
    const exactText = tokenTextBoundaries([utterance.rawText], utterance.text) !== undefined;
    return {
      utteranceId: utterance.utteranceId,
      sourceUtteranceId: utterance.utteranceId,
      rawText: utterance.rawText,
      text: utterance.text,
      beginTime: utterance.beginTime,
      endTime: utterance.endTime,
      speakerId: exactText ? utterance.speakerId : UNKNOWN_SPEAKER,
      secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
      confidence: exactText ? assignment.confidence : 0,
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
