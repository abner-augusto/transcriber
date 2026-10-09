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
    case "split":
      return ["accept", "dismiss"];
    case "comment":
      return note.author === "user" ? [] : ["done"];
  }
}

export type NoteTone = "user" | "agent";

/** Who acts next on a note in play: the user when they have an action, else the agent. null if resolved. */
export function noteTone(note: ReviewNote): NoteTone | null {
  if (!IN_PLAY.includes(note.status)) return null;
  return noteActions(note).length > 0 ? "user" : "agent";
}

/** The tone for a Segment's notes: "user" wins over "agent"; null for none. */
export function segmentTone(notes: ReviewNote[] | undefined): NoteTone | null {
  let tone: NoteTone | null = null;
  for (const note of notes ?? []) {
    const t = noteTone(note);
    if (t === "user") return "user";
    if (t === "agent") tone = "agent";
  }
  return tone;
}

/** One mark per note in play, for the audio bar. */
export function noteMarks(notes: ReviewNote[]): { id: string; time: number; tone: NoteTone }[] {
  const marks: { id: string; time: number; tone: NoteTone }[] = [];
  for (const note of notes) {
    const tone = noteTone(note);
    if (tone) marks.push({ id: note.id, time: note.start_time, tone });
  }
  return marks;
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
    case "split": {
      const target = p.target_label ?? (p.new_name !== undefined ? `new: ${p.new_name}` : null);
      return `split before "${p.preview}"${target === null ? "" : ` → ${target}`}`;
    }
    default:
      return note.body;
  }
}
