export interface DiarizationTranscriptInput {
  rawText: string;
  text: string;
  tokens: string[];
  tokenTimesMs: number[];
  beginTime: number;
  endTime: number;
}

export interface SpeakerTimelineTurn {
  beginTime: number;
  endTime: number;
  speakerId: string;
  secondarySpeakerIds: string[];
  evidenceKey?: string;
  secondaryEvidenceKeys?: string[];
}

export interface DiarizationTranscriptUpdate extends SpeakerTimelineTurn {
  utteranceId: string;
  revision: number;
  confidence: number;
}

export interface DiarizedTranscriptUtterance extends SpeakerTimelineTurn {
  utteranceId: string;
  rawText: string;
  text: string;
  overlap: boolean;
}

interface StoredUtterance extends DiarizationTranscriptInput {
  utteranceId: string;
  revision: number;
  speakerId: string;
  secondarySpeakerIds: string[];
}

const UNKNOWN_SPEAKER = 'UNKNOWN';

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

export class SpeakerDiarizationTranscriptState {
  private readonly utterances: StoredUtterance[] = [];
  private readonly turns: SpeakerTimelineTurn[] = [];

  addUtterance(input: DiarizationTranscriptInput): string {
    const utteranceId = `u${this.utterances.length + 1}`;
    const assignment = this.assignmentFor(input.beginTime, input.endTime);
    this.utterances.push({
      utteranceId,
      rawText: input.rawText,
      text: input.text,
      tokens: input.tokens.slice(),
      tokenTimesMs: input.tokenTimesMs.slice(),
      beginTime: input.beginTime,
      endTime: input.endTime,
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
      this.turns.push({
        beginTime: newTurns[i].beginTime,
        endTime: newTurns[i].endTime,
        speakerId: newTurns[i].speakerId,
        secondarySpeakerIds: newTurns[i].secondarySpeakerIds.slice(),
        evidenceKey: newTurns[i].evidenceKey,
        secondaryEvidenceKeys: newTurns[i].secondaryEvidenceKeys?.slice(),
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

  finalUtterances(): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    for (let i = 0; i < this.utterances.length; i++) {
      const utterance = this.utterances[i];
      if (utterance.tokens.length === 0 ||
        utterance.tokens.length !== utterance.tokenTimesMs.length ||
        utterance.tokens.join('') !== utterance.text) {
        result.push(this.unsplitUtterance(utterance));
        continue;
      }
      const split = this.splitByTokenSpeaker(utterance);
      if (split.map((item: DiarizedTranscriptUtterance): string => item.text).join('') !==
        utterance.text) {
        result.push(this.unsplitUtterance(utterance));
      } else {
        result.push(...split);
      }
    }
    return result;
  }

  allTurns(): SpeakerTimelineTurn[] {
    return this.turns.map((turn) => ({
      beginTime: turn.beginTime,
      endTime: turn.endTime,
      speakerId: turn.speakerId,
      secondarySpeakerIds: turn.secondarySpeakerIds.slice(),
      evidenceKey: turn.evidenceKey,
      secondaryEvidenceKeys: turn.secondaryEvidenceKeys?.slice(),
    }));
  }

  applySpeakerRemap(remap: Record<string, string>, fromTime: number = 0): DiarizationTranscriptUpdate[] {
    for (let i = 0; i < this.turns.length; i++) {
      if (this.turns[i].endTime < fromTime) continue;
      this.turns[i].speakerId = remap[this.turns[i].speakerId] ?? this.turns[i].speakerId;
      this.turns[i].secondarySpeakerIds = this.turns[i].secondarySpeakerIds
        .map((speakerId: string): string => remap[speakerId] ?? speakerId)
        .filter((speakerId: string, index: number, all: string[]): boolean =>
          speakerId !== this.turns[i].speakerId && all.indexOf(speakerId) === index);
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

  applyEvidenceRemap(remap: Record<string, string>, fromTime: number = 0): DiarizationTranscriptUpdate[] {
    for (let index = 0; index < this.turns.length; index++) {
      const turn = this.turns[index];
      if (turn.endTime < fromTime) continue;
      if (turn.evidenceKey !== undefined) {
        turn.speakerId = remap[turn.evidenceKey] ?? turn.speakerId;
      }
      const evidenceKeys = turn.secondaryEvidenceKeys ?? [];
      turn.secondarySpeakerIds = turn.secondarySpeakerIds
        .map((speakerId: string, secondaryIndex: number): string =>
          remap[evidenceKeys[secondaryIndex]] ?? speakerId)
        .filter((speakerId: string, secondaryIndex: number, all: string[]): boolean =>
          speakerId !== turn.speakerId && all.indexOf(speakerId) === secondaryIndex);
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

  private splitByTokenSpeaker(utterance: StoredUtterance): DiarizedTranscriptUtterance[] {
    const result: DiarizedTranscriptUtterance[] = [];
    let groupStart = 0;
    let active = this.turnAt(utterance.tokenTimesMs[0]);
    for (let index = 1; index <= utterance.tokens.length; index++) {
      const next = index < utterance.tokens.length ?
        this.turnAt(utterance.tokenTimesMs[index]) : undefined;
      const same = index < utterance.tokens.length &&
        (next?.speakerId ?? UNKNOWN_SPEAKER) === (active?.speakerId ?? UNKNOWN_SPEAKER) &&
        sameStrings(next?.secondarySpeakerIds ?? [], active?.secondarySpeakerIds ?? []);
      if (same) continue;
      const beginTime = groupStart === 0 ? utterance.beginTime : utterance.tokenTimesMs[groupStart];
      const endTime = index < utterance.tokens.length ?
        utterance.tokenTimesMs[index] : utterance.endTime;
      const secondarySpeakerIds = active?.secondarySpeakerIds.slice() ?? [];
      result.push({
        utteranceId: result.length === 0 ? utterance.utteranceId :
          `${utterance.utteranceId}.${result.length + 1}`,
        rawText: utterance.tokens.slice(groupStart, index).join(''),
        text: utterance.tokens.slice(groupStart, index).join(''),
        beginTime,
        endTime,
        speakerId: active?.speakerId ?? UNKNOWN_SPEAKER,
        secondarySpeakerIds,
        overlap: secondarySpeakerIds.length > 0,
      });
      groupStart = index;
      active = next;
    }
    return result;
  }

  private unsplitUtterance(utterance: StoredUtterance): DiarizedTranscriptUtterance {
    return {
      utteranceId: utterance.utteranceId,
      rawText: utterance.rawText,
      text: utterance.text,
      beginTime: utterance.beginTime,
      endTime: utterance.endTime,
      speakerId: utterance.speakerId,
      secondarySpeakerIds: utterance.secondarySpeakerIds.slice(),
      overlap: utterance.secondarySpeakerIds.length > 0,
    };
  }
}
