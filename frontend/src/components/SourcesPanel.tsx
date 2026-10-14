import { useState } from "react";
import { pointSources } from "../api";
import type { Meeting, SourceInfo } from "../types";
import { apiErrorMessage } from "../utils/apiError";
import { formatSize, pointRequest } from "../utils/sources";

interface Props {
  meeting: Meeting;
  onChanged: (meeting: Meeting) => void;
}

const STATE_STYLE: Record<SourceInfo["state"], string> = {
  present: "text-emerald-400 bg-emerald-500/10",
  missing: "text-amber-400 bg-amber-500/10",
  "not saved": "text-slate-400 bg-slate-700/40",
};

/** Where the original recording(s) live, and a way to point the Meeting at a moved one.
 *
 * A browser only learns the name of a file the user picks, never its location, so the
 * new location is typed as an absolute path; the server runs on the same machine. */
export default function SourcesPanel({ meeting, onChanged }: Props) {
  const sources = meeting.sources ?? [];
  const rows: { track: string; source?: SourceInfo }[] = sources.length
    ? sources.map((source) => ({ track: source.track, source }))
    : meeting.is_dual_track
      ? [{ track: "mic" }, { track: "system" }]
      : [{ track: "audio" }];
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  async function point(track: string) {
    setBusy(track);
    setError("");
    try {
      const updated = await pointSources(meeting.id, pointRequest(track, paths[track] ?? "", sources.length > 0));
      onChanged(updated);
      setPaths((current) => ({ ...current, [track]: "" }));
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy("");
    }
  }

  return (
    <details className="rounded-xl bg-slate-900/60 border border-slate-800/60 mb-6 group" open={!meeting.reprocessable && !!meeting.is_dual_track}>
      <summary className="cursor-pointer select-none px-4 py-3 text-sm text-slate-300 font-medium">
        Original recording
        <span className="ml-2 text-xs text-slate-500 font-normal">
          kept outside the app; reruns read it from there
        </span>
      </summary>
      <div className="px-4 pb-4 space-y-3">
        {rows.map(({ track, source }) => (
          <div key={track} className="space-y-1.5">
            <div className="flex items-center gap-2 text-sm">
              <span className="text-slate-500 uppercase text-[10px] tracking-wide w-12">{track}</span>
              <span className="text-white">{source ? source.name : "no reference"}</span>
              {source && <span className="text-xs text-slate-500">{formatSize(source.size)}</span>}
              {source && (
                <span className={`text-[10px] uppercase tracking-wide rounded px-1.5 py-0.5 ${STATE_STYLE[source.state]}`}>
                  {source.state}
                </span>
              )}
            </div>
            {source?.path && <div className="text-xs text-slate-500 break-all pl-14">{source.path}</div>}
            <div className="flex gap-2 pl-14">
              <input
                type="text"
                value={paths[track] ?? ""}
                onChange={(e) => setPaths((current) => ({ ...current, [track]: e.target.value }))}
                placeholder="Absolute path of the file, e.g. D:\Projects\Obra 12\reuniao.wav"
                className="flex-1 bg-slate-800 border border-slate-700/60 rounded-lg px-3 py-1.5 text-sm text-white placeholder-slate-600 focus:outline-none focus:border-violet-500/60"
              />
              <button
                onClick={() => point(track)}
                disabled={!(paths[track] ?? "").trim() || busy !== ""}
                className="px-3 py-1.5 text-sm bg-slate-800 text-slate-300 border border-slate-700/60 rounded-lg hover:text-white disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {busy === track ? "Checking…" : source ? "Re-point" : "Attach"}
              </button>
            </div>
          </div>
        ))}
        {error && <p className="text-sm text-red-400 pl-14">{error}</p>}
      </div>
    </details>
  );
}
