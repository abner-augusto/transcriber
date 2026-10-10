import { useMemo, useState } from "react";
import type { ReviewNote, Segment } from "../types";
import { acceptNote, answerNote, closeNote, dismissNote } from "../api";
import { apiErrorMessage } from "../utils/apiError";
import { noteActions, noteSegmentId, noteSummary, splitNotes } from "../utils/reviewNotes";
import type { NoteAction } from "../utils/reviewNotes";

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

const KIND_LABELS: Record<ReviewNote["kind"], string> = {
  comment: "comment",
  question: "question",
  text: "text",
  speaker_name: "name",
  speaker_move: "move",
  speaker_merge: "merge",
  split: "split",
};

const ACTION_LABELS: Record<Exclude<NoteAction, "answer">, string> = {
  accept: "Accept",
  acceptWithoutLearning: "Accept without teaching",
  acceptWithoutProfile: "Accept without saving voice",
  dismiss: "Dismiss",
  done: "Done",
};

interface Props {
  notes: ReviewNote[];
  segments: Segment[];
  onUpdate: () => void;
  onSeek: (time: number) => void;
  meetingId: string;
}

export default function ReviewPanel({ notes, segments, onUpdate, onSeek }: Props) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<Record<string, string>>({});
  const [answeringId, setAnsweringId] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [showResolved, setShowResolved] = useState(false);

  const { open, resolved } = useMemo(() => splitNotes(notes), [notes]);

  async function run(note: ReviewNote, action: () => Promise<void>) {
    setBusyId(note.id);
    setErrors((prev) => {
      const { [note.id]: _drop, ...rest } = prev;
      return rest;
    });
    try {
      await action();
      onUpdate();
    } catch (err) {
      setErrors((prev) => ({ ...prev, [note.id]: apiErrorMessage(err) }));
    } finally {
      setBusyId(null);
    }
  }

  function accept(note: ReviewNote, opts: { learn?: boolean; save_profile?: boolean }) {
    return run(note, async () => {
      const { warning } = await acceptNote(note.id, opts);
      if (warning) setWarnings((prev) => ({ ...prev, [note.id]: warning }));
    });
  }

  function perform(note: ReviewNote, action: Exclude<NoteAction, "answer">) {
    switch (action) {
      case "accept":
        return accept(note, {});
      case "acceptWithoutLearning":
        return accept(note, { learn: false });
      case "acceptWithoutProfile":
        return accept(note, { save_profile: false });
      case "dismiss":
        return run(note, async () => {
          await dismissNote(note.id);
        });
      case "done":
        return run(note, async () => {
          await closeNote(note.id);
        });
    }
  }

  function sendAnswer(note: ReviewNote) {
    const text = answerText.trim();
    if (!text) return;
    return run(note, async () => {
      await answerNote(note.id, text);
      setAnsweringId(null);
      setAnswerText("");
    });
  }

  return (
    <div className="rounded-xl bg-slate-900/80 border border-slate-800/50 p-5 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-white text-sm">Review</h3>
        <span className="text-xs text-slate-500">{open.length} open</span>
      </div>

      {open.length === 0 && <p className="text-xs text-slate-500">Nothing to review.</p>}

      <div className="space-y-2">
        {open.map((note) => {
          const actions = noteActions(note);
          const summary = noteSummary(note);
          const attached = noteSegmentId(note, segments) !== null;
          const busy = busyId === note.id;
          return (
            <div key={note.id} className="rounded-lg p-3 bg-slate-800/30">
              <div className="flex items-center gap-2 text-[10px]">
                <button
                  onClick={() => onSeek(note.start_time)}
                  className="font-mono text-slate-500 hover:text-violet-400 transition"
                  title="Play from here"
                >
                  {formatTime(note.start_time)}
                </button>
                <span
                  className={`px-1.5 py-0.5 rounded font-medium ${
                    note.author === "user"
                      ? "text-violet-400 bg-violet-500/10"
                      : "text-emerald-400 bg-emerald-500/10"
                  }`}
                >
                  {note.author}
                </span>
                <span className="text-slate-500">{KIND_LABELS[note.kind]}</span>
                {!attached && <span className="text-slate-600">passage changed</span>}
              </div>

              <p className="text-sm text-slate-200 mt-1.5 break-words">{summary}</p>
              {note.body !== summary && (
                <p className="text-xs text-slate-500 mt-1 break-words">{note.body}</p>
              )}
              {note.answer && (
                <p className="text-xs text-slate-400 mt-1 break-words">Your answer: {note.answer}</p>
              )}

              {answeringId === note.id ? (
                <div className="mt-2">
                  <textarea
                    value={answerText}
                    onChange={(e) => setAnswerText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setAnsweringId(null);
                    }}
                    autoFocus
                    rows={2}
                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-2 py-1.5 text-xs text-white resize-none focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                  />
                  <div className="flex gap-3 mt-1">
                    <button
                      onClick={() => sendAnswer(note)}
                      disabled={busy || !answerText.trim()}
                      className="text-xs text-violet-400 hover:text-violet-300 disabled:opacity-40"
                    >
                      Send
                    </button>
                    <button
                      onClick={() => setAnsweringId(null)}
                      className="text-xs text-slate-500 hover:text-slate-300"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                actions.length > 0 && (
                  <div className="flex flex-wrap gap-x-3 gap-y-1 mt-2">
                    {actions.map((action) =>
                      action === "answer" ? (
                        <button
                          key={action}
                          onClick={() => {
                            setAnsweringId(note.id);
                            setAnswerText("");
                          }}
                          disabled={busy}
                          className="text-xs text-violet-400 hover:text-violet-300 disabled:opacity-40"
                        >
                          Answer
                        </button>
                      ) : (
                        <button
                          key={action}
                          onClick={() => perform(note, action)}
                          disabled={busy}
                          className={`text-xs disabled:opacity-40 ${
                            action === "accept" || action === "done"
                              ? "text-violet-400 hover:text-violet-300"
                              : "text-slate-500 hover:text-slate-300"
                          }`}
                        >
                          {ACTION_LABELS[action]}
                        </button>
                      ),
                    )}
                  </div>
                )
              )}

              {errors[note.id] && <p className="text-xs text-red-400 mt-1.5">{errors[note.id]}</p>}
              {warnings[note.id] && <p className="text-xs text-amber-400 mt-1.5">{warnings[note.id]}</p>}
            </div>
          );
        })}
      </div>

      {resolved.length > 0 && (
        <div className="mt-4">
          <button
            onClick={() => setShowResolved(!showResolved)}
            className="text-xs text-slate-500 hover:text-slate-300 transition"
          >
            {showResolved ? "▾" : "▸"} Resolved ({resolved.length})
          </button>
          {showResolved && (
            <div className="space-y-2 mt-2">
              {resolved.map((note) => (
                <div key={note.id} className="rounded-lg p-3 bg-slate-800/20">
                  <div className="flex items-center gap-2 text-[10px]">
                    <button
                      onClick={() => onSeek(note.start_time)}
                      className="font-mono text-slate-600 hover:text-violet-400 transition"
                      title="Play from here"
                    >
                      {formatTime(note.start_time)}
                    </button>
                    <span className="text-slate-600">{KIND_LABELS[note.kind]}</span>
                    <span className="text-slate-500">{note.status}</span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 break-words">{noteSummary(note)}</p>
                  {note.answer && <p className="text-xs text-slate-500 mt-1 break-words">Answer: {note.answer}</p>}
                  {note.reply && <p className="text-xs text-slate-500 mt-1 break-words">Reply: {note.reply}</p>}
                  {warnings[note.id] && <p className="text-xs text-amber-400 mt-1">{warnings[note.id]}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
