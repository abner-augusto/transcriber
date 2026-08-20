import { useEffect, useState } from "react";
import { getModelSettings, duplicateMeeting } from "../api";
import type { Preset } from "../types";

interface Props {
  meetingId: string;
  currentPresetId: string | null;
  onClose: () => void;
  onCreated: (newMeetingId: string) => void;
}

export default function DuplicateReprocessDialog({ meetingId, currentPresetId, onClose, onCreated }: Props) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selected, setSelected] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getModelSettings().then((data) => {
      setPresets(data.presets);
      const fallback = data.presets.find((p) => p.id !== currentPresetId) || data.presets[0];
      setSelected(fallback?.id || "");
    });
  }, [currentPresetId]);

  async function handleSubmit() {
    if (!selected) return;
    setSubmitting(true);
    setError("");
    try {
      const copy = await duplicateMeeting(meetingId, selected);
      onCreated(copy.id);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "Failed to create copy");
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-white mb-1">Duplicate &amp; reprocess</h2>
        <p className="text-sm text-slate-500 mb-5">
          Creates a new meeting from the same audio and transcribes it with a different backend. The original is left untouched.
        </p>

        <div className="space-y-2">
          {presets.map((p) => (
            <button
              key={p.id}
              onClick={() => setSelected(p.id)}
              className={`w-full text-left p-4 rounded-xl border transition-all ${
                selected === p.id
                  ? "border-violet-500/50 bg-violet-500/10"
                  : "border-slate-800/50 hover:bg-slate-800/50 hover:border-slate-700/50"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white text-sm">{p.name}</span>
                {p.id === currentPresetId && (
                  <span className="text-[10px] uppercase tracking-wide text-slate-500 bg-slate-800 rounded px-1.5 py-0.5">current</span>
                )}
                {!p.available && (
                  <span className="text-[10px] uppercase tracking-wide text-amber-400 bg-amber-500/10 rounded px-1.5 py-0.5">unavailable</span>
                )}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">{p.engine}</p>
            </button>
          ))}
          {presets.length === 0 && (
            <p className="text-sm text-slate-500 py-4 text-center">No presets configured.</p>
          )}
        </div>

        {error && <p className="text-sm text-red-400 mt-4">{error}</p>}

        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!selected || submitting}
            className="flex-1 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {submitting ? "Creating…" : "Create copy & start"}
          </button>
        </div>
      </div>
    </div>
  );
}
