import type { Correction, Segment } from "../types";

export interface CorrectionEntry {
  segmentId: string;
  order: number;
  correction: Correction;
}

/**
 * Every Vocabulary Correction in the Meeting that can be acted on, split into those
 * awaiting review and those already confirmed, each in time order. Corrections without
 * offsets predate plan 041, cannot be undone, and are left out.
 */
export function meetingCorrections(segments: Segment[]): {
  toReview: CorrectionEntry[];
  confirmed: CorrectionEntry[];
} {
  const toReview: CorrectionEntry[] = [];
  const confirmed: CorrectionEntry[] = [];
  for (const segment of segments) {
    for (const correction of segment.corrections ?? []) {
      if (correction.text_start === undefined || correction.text_end === undefined) continue;
      const entry = { segmentId: segment.id, order: segment.order, correction };
      (correction.confirmed === true ? confirmed : toReview).push(entry);
    }
  }
  const byTime = (a: CorrectionEntry, b: CorrectionEntry) => a.correction.start - b.correction.start;
  return { toReview: toReview.sort(byTime), confirmed: confirmed.sort(byTime) };
}
