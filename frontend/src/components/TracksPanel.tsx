import { useState } from "react";
import { setTracks } from "../api";
import type { Meeting } from "../types";
import { apiErrorMessage } from "../utils/apiError";
import { describeTrack, trackKey, tracksRequest } from "../utils/tracks";

interface Props {
  meeting: Meeting;
  onChanged: (meeting: Meeting) => void;
}

/** The tracks the app found in the uploaded file, and which it will read as the mic and the system.
 *
 * Shown before processing: the choice decides what audio the Meeting is made from. */
export default function TracksPanel({ meeting, onChanged }: Props) {
  const layout = meeting.track_layout;
  const savedMic = layout?.mic ?? layout?.audio;
  const savedMicKey = savedMic ? trackKey(savedMic) : "";
  const savedSystemKey = layout?.system ? trackKey(layout.system) : "";
  const [mic, setMic] = useState(savedMicKey);
  const [system, setSystem] = useState(savedSystemKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!layout) return null;

  const request = tracksRequest(mic, system);
  const unchanged = mic === savedMicKey && system === savedSystemKey;

  async function apply() {
    if (!request) return;
    setBusy(true);
    setError("");
    try {
      onChanged(await setTracks(meeting.id, request));
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const options = layout.tracks.map((track) => (
    <option key={trackKey(track)} value={trackKey(track)}>
      {describeTrack(track)}
    </option>
  ));
  const select = "flex-1 bg-slate-800 border border-slate-700/60 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-violet-500/60";

  return (
    <details className="rounded-xl bg-slate-900/60 border border-slate-800/60 mb-6" open>
      <summary className="cursor-pointer select-none px-4 py-3 text-sm text-slate-300 font-medium">
        Tracks in this file
        <span className="ml-2 text-xs text-slate-500 font-normal">
          {layout.manual ? "chosen by you" : "found by the app — check before processing"}
        </span>
      </summary>
      <div className="px-4 pb-4 space-y-3">
        <label className="flex items-center gap-3 text-sm">
          <span className="w-24 text-slate-500 uppercase text-[10px] tracking-wide">Microphone</span>
          <select value={mic} onChange={(e) => setMic(e.target.value)} className={select}>
            {options}
          </select>
        </label>
        <label className="flex items-center gap-3 text-sm">
          <span className="w-24 text-slate-500 uppercase text-[10px] tracking-wide">System audio</span>
          <select value={system} onChange={(e) => setSystem(e.target.value)} className={select}>
            <option value="">None — read the file as one track</option>
            {options}
          </select>
        </label>
        {!request && mic !== "" && mic === system && (
          <p className="text-sm text-amber-400">The microphone and the system audio cannot be the same track.</p>
        )}
        <div className="flex items-center gap-3 pl-[108px]">
          <button
            onClick={apply}
            disabled={!request || unchanged || busy}
            className="px-3 py-1.5 text-sm bg-slate-800 text-slate-300 border border-slate-700/60 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? "Saving…" : "Use these tracks"}
          </button>
          {error && <span className="text-sm text-red-400">{error}</span>}
        </div>
      </div>
    </details>
  );
}
