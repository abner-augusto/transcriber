import { describe, it, expect } from "vitest";
import type { ReviewNote, Segment } from "../types";
import {
  noteActions,
  noteMarks,
  noteSegmentId,
  noteSummary,
  noteTone,
  notesBySegment,
  segmentTone,
  splitNotes,
} from "./reviewNotes";

function segment(id: string, start: number, end: number): Segment {
  return {
    id, meeting_id: "m", speaker_id: null, speaker_label: null, speaker_name: null,
    speaker_color: null, start_time: start, end_time: end, text: "t", original_text: null,
    order: 0, is_edited: false, confidence: null,
  };
}

function note(overrides: Partial<ReviewNote>): ReviewNote {
  return {
    id: "n", meeting_id: "m", start_time: 0, end_time: 1, author: "agent", kind: "comment",
    body: "b", payload: null, status: "open", answer: null, reply: null,
    created_at: null, resolved_at: null, ...overrides,
  };
}

describe("noteTone", () => {
  it("is user for an open agent question (the user must answer)", () => {
    expect(noteTone(note({ kind: "question", author: "agent", status: "open" }))).toBe("user");
  });

  it("is agent for an answered question", () => {
    expect(noteTone(note({ kind: "question", status: "answered" }))).toBe("agent");
  });

  it("is agent for an open comment written by the user", () => {
    expect(noteTone(note({ kind: "comment", author: "user", status: "open" }))).toBe("agent");
  });

  it("is user for an open comment written by the agent", () => {
    expect(noteTone(note({ kind: "comment", author: "agent", status: "open" }))).toBe("user");
  });

  it("is null for a resolved note", () => {
    expect(noteTone(note({ status: "accepted" }))).toBeNull();
    expect(noteTone(note({ status: "dismissed" }))).toBeNull();
    expect(noteTone(note({ status: "done" }))).toBeNull();
  });
});

describe("segmentTone", () => {
  it("is null without notes", () => {
    expect(segmentTone(undefined)).toBeNull();
    expect(segmentTone([])).toBeNull();
  });

  it("lets user win over agent", () => {
    const mixed = [
      note({ id: "a", kind: "comment", author: "user" }),
      note({ id: "b", kind: "question", author: "agent" }),
    ];
    expect(segmentTone(mixed)).toBe("user");
  });

  it("is agent when every note waits for the agent", () => {
    expect(segmentTone([note({ kind: "comment", author: "user" })])).toBe("agent");
  });
});

describe("noteMarks", () => {
  it("makes one mark per note in play at its start_time, skipping resolved ones", () => {
    const marks = noteMarks([
      note({ id: "q", kind: "question", start_time: 12.5 }),
      note({ id: "c", kind: "comment", author: "user", start_time: 3 }),
      note({ id: "r", kind: "comment", status: "done", start_time: 99 }),
    ]);
    expect(marks).toEqual([
      { id: "q", time: 12.5, tone: "user" },
      { id: "c", time: 3, tone: "agent" },
    ]);
  });
});

describe("noteSegmentId", () => {
  const segments = [segment("a", 0, 5), segment("b", 5, 10), segment("c", 10.5, 15)];

  it("picks the Segment whose start and end are both within 1.5 s", () => {
    expect(noteSegmentId(note({ start_time: 5.2, end_time: 9.8 }), segments)).toBe("b");
  });

  it("prefers the nearest by |dstart|+|dend|", () => {
    // Both are candidates for (0.7, 5.7); "y" is nearer (0.1+0.1) than "x" (0.7+0.7).
    const close = [segment("x", 0, 5), segment("y", 0.8, 5.8)];
    expect(noteSegmentId(note({ start_time: 0.7, end_time: 5.7 }), close)).toBe("y");
  });

  it("returns null when no Segment is within tolerance, even if only the start matches", () => {
    expect(noteSegmentId(note({ start_time: 100, end_time: 105 }), segments)).toBeNull();
    expect(noteSegmentId(note({ start_time: 5, end_time: 20 }), segments)).toBeNull();
  });

  it("treats exactly 1.5 s as out of range, like the backend", () => {
    expect(noteSegmentId(note({ start_time: 1.5, end_time: 6.5 }), [segment("a", 0, 5)])).toBeNull();
  });
});

describe("notesBySegment", () => {
  const segments = [segment("a", 0, 5), segment("b", 5, 10)];

  it("groups notes in play by Segment and leaves resolved ones out", () => {
    const notes = [
      note({ id: "1", start_time: 0, end_time: 5, status: "open" }),
      note({ id: "2", start_time: 0, end_time: 5, kind: "question", status: "answered" }),
      note({ id: "3", start_time: 0, end_time: 5, status: "done" }),
      note({ id: "4", start_time: 5, end_time: 10, kind: "text", status: "accepted" }),
      note({ id: "5", start_time: 5, end_time: 10, kind: "text", status: "dismissed" }),
      note({ id: "6", start_time: 50, end_time: 55, status: "open" }),
    ];
    const grouped = notesBySegment(notes, segments);
    expect([...grouped.keys()]).toEqual(["a"]);
    expect(grouped.get("a")!.map((n) => n.id)).toEqual(["1", "2"]);
  });
});

describe("splitNotes", () => {
  it("lists open and answered by start_time, resolved newest first", () => {
    const { open, resolved } = splitNotes([
      note({ id: "late", start_time: 30, status: "open" }),
      note({ id: "early", start_time: 3, kind: "question", status: "answered" }),
      note({ id: "old", status: "done", resolved_at: "2026-10-01T10:00:00" }),
      note({ id: "new", status: "dismissed", resolved_at: "2026-10-02T10:00:00" }),
      note({ id: "mid", status: "accepted", resolved_at: "2026-10-01T12:00:00" }),
    ]);
    expect(open.map((n) => n.id)).toEqual(["early", "late"]);
    expect(resolved.map((n) => n.id)).toEqual(["new", "mid", "old"]);
  });
});

describe("noteActions", () => {
  it("open question: answer, dismiss", () => {
    expect(noteActions(note({ kind: "question" }))).toEqual(["answer", "dismiss"]);
  });

  it("answered question: nothing for the user", () => {
    expect(noteActions(note({ kind: "question", status: "answered" }))).toEqual([]);
  });

  it("open text: accept, accept without teaching, dismiss", () => {
    expect(noteActions(note({ kind: "text" }))).toEqual(["accept", "acceptWithoutLearning", "dismiss"]);
  });

  it("open speaker_name: accept, accept without saving the voice, dismiss", () => {
    expect(noteActions(note({ kind: "speaker_name" }))).toEqual(["accept", "acceptWithoutProfile", "dismiss"]);
  });

  it("open speaker_move and speaker_merge: accept, dismiss", () => {
    expect(noteActions(note({ kind: "speaker_move" }))).toEqual(["accept", "dismiss"]);
    expect(noteActions(note({ kind: "speaker_merge" }))).toEqual(["accept", "dismiss"]);
  });

  it("open split: accept, dismiss; resolved split: none", () => {
    expect(noteActions(note({ kind: "split" }))).toEqual(["accept", "dismiss"]);
    expect(noteActions(note({ kind: "split", status: "accepted" }))).toEqual([]);
    expect(noteActions(note({ kind: "split", status: "dismissed" }))).toEqual([]);
  });

  it("open comment: the user may close the agent's, not their own", () => {
    expect(noteActions(note({ kind: "comment", author: "agent" }))).toEqual(["done"]);
    expect(noteActions(note({ kind: "comment", author: "user" }))).toEqual([]);
  });

  it("resolved notes have no actions", () => {
    for (const status of ["accepted", "dismissed", "done"] as const) {
      expect(noteActions(note({ kind: "text", status }))).toEqual([]);
    }
  });
});

describe("noteSummary", () => {
  it("text shows the change", () => {
    const n = note({ kind: "text", payload: { expected_text: "olá mundo", proposed_text: "Olá, mundo" } });
    expect(noteSummary(n)).toBe('"olá mundo" → "Olá, mundo"');
  });

  it("speaker_name shows label and name", () => {
    expect(noteSummary(note({ kind: "speaker_name", payload: { label: "SPEAKER_00", name: "Ana" } }))).toBe(
      "SPEAKER_00 → Ana",
    );
  });

  it("speaker_move shows the target Speaker or the new one", () => {
    expect(noteSummary(note({ kind: "speaker_move", payload: { target_label: "SPEAKER_01" } }))).toBe(
      "→ SPEAKER_01",
    );
    expect(noteSummary(note({ kind: "speaker_move", payload: { new_name: "Bia" } }))).toBe("→ new: Bia");
  });

  it("speaker_merge shows source and target", () => {
    const n = note({ kind: "speaker_merge", payload: { source_label: "SPEAKER_02", target_label: "SPEAKER_00" } });
    expect(noteSummary(n)).toBe("SPEAKER_02 → SPEAKER_00");
  });

  it("split shows the first words of the second half, and the target when there is one", () => {
    const payload = { at: 12.5, preview: "quem manda aqui" };
    expect(noteSummary(note({ kind: "split", payload }))).toBe('split before "quem manda aqui"');
    expect(noteSummary(note({ kind: "split", payload: { ...payload, target_label: "SPEAKER_01" } }))).toBe(
      'split before "quem manda aqui" → SPEAKER_01',
    );
    expect(noteSummary(note({ kind: "split", payload: { ...payload, new_name: "Bia" } }))).toBe(
      'split before "quem manda aqui" → new: Bia',
    );
  });

  it("question and comment show the body", () => {
    expect(noteSummary(note({ kind: "question", body: "Quem fala aqui?" }))).toBe("Quem fala aqui?");
    expect(noteSummary(note({ kind: "comment", body: "Ruído ao fundo" }))).toBe("Ruído ao fundo");
  });
});
