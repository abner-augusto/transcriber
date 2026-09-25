import type { PreferencesForm } from "./usePreferencesForm";
import { engineHealthDot } from "../../utils/engineHealth";

interface Props {
  form: PreferencesForm;
}

export default function DiarizationTab({ form }: Props) {
  const {
    diarizerEngine, setDiarizerEngine, diarizers, hfToken, setHfToken,
    clusterThreshold, setClusterThreshold, switchPenalty, setSwitchPenalty,
  } = form;
  const usesPyannote = diarizerEngine === "pyannote";

  return (
    <>
      <div>
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2.5">Diarizer Engine</p>
        <div className="space-y-2">
          {diarizers.map((diarizer) => (
            <div key={diarizer.id}
              className="bg-slate-800/30 hover:bg-slate-800/50 border border-slate-700/20 rounded-xl px-3.5 py-2.5 transition">
              <label
                className={`flex items-start gap-3 min-w-0 ${diarizer.state === "blocked" ? "cursor-not-allowed" : "cursor-pointer"}`}
                title={diarizer.state === "ready" ? undefined : diarizer.summary}
              >
                <input
                  type="radio"
                  name="diarizer-engine"
                  checked={diarizerEngine === diarizer.id}
                  disabled={diarizer.state === "blocked"}
                  onChange={() => setDiarizerEngine(diarizer.id)}
                  className="accent-violet-600 mt-1"
                />
                <span className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${engineHealthDot(diarizer.state)}`} />
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-medium text-slate-200">{diarizer.name}</span>
                  <p className="text-xs text-slate-500 mt-0.5">{diarizer.description}</p>
                  {diarizer.state !== "ready" && (
                    <p className="text-[11px] text-amber-400/90 mt-1 flex items-center gap-1">
                      <span>⚠️</span> {diarizer.summary}
                    </p>
                  )}
                  {diarizer.checks.length > 0 && (
                    <details className="text-[10px] text-slate-500 mt-1">
                      <summary className="cursor-pointer">Health checks</summary>
                      <ul className="mt-1 space-y-0.5">
                        {diarizer.checks.map((check) => (
                          <li key={check.code} className={check.passed ? "text-slate-500" : "text-amber-400/90"}>
                            {check.passed ? "✓" : "×"} {check.message}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              </label>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-slate-800/30 border border-slate-700/20 rounded-xl px-3.5 py-3 space-y-1.5">
        <p className="text-xs text-slate-400">Presets with native diarization (such as VibeVoice) do not use this choice.</p>
        <p className="text-xs text-slate-400">On dual-track Meetings, the Diarizer separates remote speakers; the host comes from the mic track.</p>
      </div>

      {usesPyannote && (
        <>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Hugging Face token</label>
            <p className="text-xs text-slate-500 mb-1.5">
              pyannote downloads its gated models with it.{" "}
              <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer"
                className="text-violet-400 hover:text-violet-300">huggingface.co/settings/tokens</a>
            </p>
            <input type="password" value={hfToken} onChange={(e) => setHfToken(e.target.value)}
              className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              placeholder="hf_..." autoComplete="off" />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Speaker separation</label>
            <p className="text-xs text-slate-500 mb-2">
              Clustering threshold for diarization. Lower splits more readily (one person can
              become several speakers); higher merges more readily (two people can collapse into
              one). Leave on the model default unless speakers are visibly wrong.
            </p>
            <div className="flex items-center gap-3">
              <input type="range" min={0.5} max={0.9} step={0.01}
                value={clusterThreshold ?? 0.7}
                disabled={clusterThreshold == null}
                onChange={(e) => setClusterThreshold(parseFloat(e.target.value))}
                className="flex-1 accent-violet-600 disabled:opacity-40" />
              <span className="text-xs text-slate-400 font-mono w-10 text-right">
                {clusterThreshold == null ? "—" : clusterThreshold.toFixed(2)}
              </span>
            </div>
            <div className="flex text-[10px] text-slate-600 mt-1">
              <span>more speakers</span><span className="flex-1" /><span>fewer speakers</span>
            </div>
            <label className="flex items-center gap-2 mt-2 text-xs text-slate-400 cursor-pointer">
              <input type="checkbox" checked={clusterThreshold == null}
                onChange={(e) => setClusterThreshold(e.target.checked ? null : 0.7)}
                className="accent-violet-600" />
              Use model default
            </label>
          </div>
        </>
      )}

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">Speaker attribution smoothing</label>
        <p className="text-xs text-slate-500 mb-2">
          Penalty for switching speakers between nearby words. Higher values suppress isolated
          switches; set to zero to follow timestamp evidence directly.
        </p>
        <div className="flex items-center gap-3">
          <input type="range" min={0} max={2} step={0.05}
            value={switchPenalty}
            onChange={(e) => setSwitchPenalty(parseFloat(e.target.value))}
            className="flex-1 accent-violet-600" />
          <span className="text-xs text-slate-400 font-mono w-10 text-right">{switchPenalty.toFixed(2)}</span>
        </div>
        <div className="flex text-[10px] text-slate-600 mt-1">
          <span>more responsive</span><span className="flex-1" /><span>more stable</span>
        </div>
      </div>
    </>
  );
}
