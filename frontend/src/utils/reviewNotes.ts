import type { ReviewNote, Segment } from "../types";

// Mirrors meeting_store.EDIT_TIME_TOLERANCE on the backend. Change both together.
export const NOTE_TOLERANCE_SECONDS = 1.5;

export type NoteAction =
  | "answer"
  | "accept"
  | "acceptWithoutLearning"
  | "acceptWithoutProfile"
  | "dismiss"
  | "done";

const IN_PLAY = ["open", "answered"];

/** The Segment a note points at now: both ends within tolerance, nearest by |Δstart|+|Δend|. */
export function noteSegmentId(note: ReviewNote, segments: Segment[]): string | null {
  let best: { id: string; distance: number } | null = null;
  for (const seg of segments) {
    const dStart = Math.abs(seg.start_time - note.start_time);
    const dEnd = Math.abs(seg.end_time - note.end_time);
    if (dStart >= NOTE_TOLERANCE_SECONDS || dEnd >= NOTE_TOLERANCE_SECONDS) continue;
    const distance = dStart + dEnd;
    if (best === null || distance < best.distance) best = { id: seg.id, distance };
  }
  return best ? best.id : null;
}

/** Notes still in play (open or answered), grouped by the Segment they point at. */
export function notesBySegment(notes: ReviewNote[], segments: Segment[]): Map<string, ReviewNote[]> {
  const grouped = new Map<string, ReviewNote[]>();
  for (const note of notes) {
    if (!IN_PLAY.includes(note.status)) continue;
    const segmentId = noteSegmentId(note, segments);
    if (segmentId === null) continue;
    const list = grouped.get(segmentId);
    if (list) list.push(note);
    else grouped.set(segmentId, [note]);
  }
  return grouped;
}

export function splitNotes(notes: ReviewNote[]): { open: ReviewNote[]; resolved: ReviewNote[] } {
  const open = notes.filter((n) => IN_PLAY.includes(n.status)).sort((a, b) => a.start_time - b.start_time);
  const resolvedAt = (n: ReviewNote) => n.resolved_at ?? n.created_at ?? "";
  const resolved = notes
    .filter((n) => !IN_PLAY.includes(n.status))
    .sort((a, b) => resolvedAt(b).localeCompare(resolvedAt(a)));
  return { open, resolved };
}

export function noteActions(note: ReviewNote): NoteAction[] {
  if (note.status !== "open") return [];
  switch (note.kind) {
    case "question":
      return ["answer", "dismiss"];
    case "text":
      return ["accept", "acceptWithoutLearning", "dismiss"];
    case "speaker_name":
      return ["accept", "acceptWithoutProfile", "dismiss"];
    case "speaker_move":
    case "speaker_merge":
      return ["accept", "dismiss"];
    case "comment":
      return note.author === "user" ? [] : ["done"];
  }
}

/** One line for the list. */
export function noteSummary(note: ReviewNote): string {
  const p = note.payload ?? {};
  switch (note.kind) {
    case "text":
      return `"${p.expected_text}" → "${p.proposed_text}"`;
    case "speaker_name":
      return `${p.label} → ${p.name}`;
    case "speaker_move":
      return `→ ${p.target_label ?? `new: ${p.new_name}`}`;
    case "speaker_merge":
      return `${p.source_label} → ${p.target_label}`;
    default:
      return note.body;
  }
}
