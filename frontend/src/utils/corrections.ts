import type { Correction } from "../types";

export type CorrectionPiece = { text: string; correction?: Correction };

/**
 * Split a Segment's text into plain pieces and pieces a Vocabulary Correction produced.
 *
 * The pieces always join back to `text`. A Correction without usable offsets (old data,
 * out of range, empty) or overlapping an earlier one is left unmarked.
 */
export function correctionPieces(text: string, corrections: Correction[]): CorrectionPiece[] {
  const placed = corrections
    .filter(
      (c): c is Correction & { text_start: number; text_end: number } =>
        c.text_start != null &&
        c.text_end != null &&
        c.text_start >= 0 &&
        c.text_end <= text.length &&
        c.text_start < c.text_end,
    )
    .sort((a, b) => a.text_start - b.text_start);

  const pieces: CorrectionPiece[] = [];
  let cursor = 0;
  for (const c of placed) {
    if (c.text_start < cursor) continue;
    if (c.text_start > cursor) pieces.push({ text: text.slice(cursor, c.text_start) });
    pieces.push({ text: text.slice(c.text_start, c.text_end), correction: c });
    cursor = c.text_end;
  }
  if (cursor < text.length || pieces.length === 0) pieces.push({ text: text.slice(cursor) });
  return pieces;
}
