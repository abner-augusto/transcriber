import type { ModelSettings } from "../../types";
import { engineMeta } from "../../engineMetadata";
import { engineHealthDot } from "../../utils/engineHealth";
import type { PresetEditor } from "./usePresetEditor";

interface Props {
  settings: ModelSettings;
  editor: PresetEditor;
}

export default function PresetTab({ settings, editor }: Props) {
  const {
    showAddPreset, setShowAddPreset, editingPresetId,
    newName, setNewName, newEngine,
    newModelPath, setNewModelPath, newAlignerPath, setNewAlignerPath,
    newLanguage, setNewLanguage, newDecoder, setNewDecoder, newDevice, setNewDevice,
    addError, defaultSaving,
    handleEngineChange, resetPresetForm, startEditPreset, cancelPresetForm,
    handleSavePreset, handleDeletePreset, handleSetDefault,
  } = editor;
  const currentEngineMeta = engineMeta(newEngine);

  return (
    <>

      {/* Transcription presets list */}
      <div>
        <div className="flex items-center justify-between mb-2.5">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Transcription Presets</p>
          <button
            type="button"
            onClick={() => {
              if (showAddPreset) {
                cancelPresetForm();
              } else {
                resetPresetForm();
                setShowAddPreset(true);
              }
            }}
            className="text-xs text-violet-400 hover:text-violet-300 transition flex items-center gap-1 font-medium"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={showAddPreset ? "M6 18L18 6M6 6l12 12" : "M12 4v16m8-8H4"} />
            </svg>
            {showAddPreset ? "Cancel" : "Add preset"}
          </button>
        </div>

        <div className="space-y-2">
          {settings.presets.map((p) => {
            const meta = engineMeta(p.engine);

            return (
              <div
                key={p.id}
                className="bg-slate-800/30 hover:bg-slate-800/50 border border-slate-700/20 rounded-xl px-3.5 py-2.5 transition flex items-center justify-between gap-3"
              >
                <label
                  className="flex items-start gap-3 min-w-0 flex-1 cursor-pointer"
                  title={p.state === "ready" ? undefined : p.summary}
                >
                  <input
                    type="radio"
                    name="default-preset"
                    checked={settings.default_preset === p.id}
                    disabled={p.state === "blocked" || defaultSaving === p.id}
                    onChange={() => handleSetDefault(p.id)}
                    className="accent-violet-600 mt-1"
                  />
                  <span
                    className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${engineHealthDot(p.state)}`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-slate-200">{p.name}</span>
                      <span className="text-[10px] text-slate-400 uppercase tracking-wider font-mono bg-slate-800 border border-slate-700/50 px-1.5 py-0.5 rounded flex-shrink-0">
                        {p.engine}
                      </span>

                      {/* Diarization status badge */}
                      <span
                        className={`text-[10px] px-2 py-0.5 rounded-full font-medium flex items-center gap-1 flex-shrink-0 border ${meta.badgeStyle}`}
                        title={meta.badgeTitle}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full inline-block ${meta.badgeDot}`} />
                        {meta.badgeText}
                      </span>

                      {settings.default_preset === p.id && (
                        <span className="text-[10px] bg-violet-500/20 text-violet-300 border border-violet-500/30 px-1.5 py-0.5 rounded-full font-medium flex-shrink-0">
                          default
                        </span>
                      )}
                    </div>

                    {/* Detail subline */}
                    <div className="text-xs text-slate-400 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 mt-1">
                      <span className="font-mono text-slate-400 truncate max-w-xs">{p.model_path}</span>
                      {p.language && (
                        <span className="text-slate-400 text-[11px]">
                          Lang: <span className="text-slate-300">{p.language}</span>
                        </span>
                      )}
                      {p.aligner_path && (
                        <span className="text-slate-500 text-[11px]">
                          Aligner: <span className="font-mono text-slate-400">{p.aligner_path.split("/").pop()}</span>
                        </span>
                      )}
                      {p.device && (
                        <span className="text-[10px] text-slate-400 uppercase bg-slate-800 border border-slate-700/50 px-1.5 py-0.2 rounded">
                          {p.device}
                        </span>
                      )}
                      {p.decoder && (
                        <span className="text-[10px] text-slate-400 uppercase bg-slate-800 border border-slate-700/50 px-1.5 py-0.2 rounded">
                          {p.decoder}
                        </span>
                      )}
                    </div>

                    {p.state !== "ready" && (
                      <p className="text-[11px] text-amber-400/90 mt-1 flex items-center gap-1">
                        <span>⚠️</span> {p.summary}
                      </p>
                    )}
                    {p.checks.length > 0 && (
                      <details className="text-[10px] text-slate-500 mt-1">
                        <summary className="cursor-pointer">Health checks</summary>
                        <ul className="mt-1 space-y-0.5">
                          {p.checks.map((check) => (
                            <li key={check.code} className={check.passed ? "text-slate-500" : "text-amber-400/90"}>
                              {check.passed ? "✓" : "×"} {check.message}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                </label>

                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => startEditPreset(p)}
                    className="text-slate-500 hover:text-violet-300 transition p-1.5 rounded-lg hover:bg-slate-700/30"
                    title={`Edit preset ${p.name}`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeletePreset(p.id)}
                    className="text-slate-600 hover:text-red-400 transition p-1.5 rounded-lg hover:bg-slate-700/30"
                    title={`Delete preset ${p.name}`}
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              </div>
            );
          })}
          {settings.presets.length === 0 && (
            <p className="text-xs text-slate-600">No presets configured yet.</p>
          )}
        </div>
        <p className="text-[10px] text-slate-600 mt-2">
          Select the radio to make a Preset the default. Blocked Presets cannot process Meetings; degraded Presets use the stated fallback.
        </p>

        {/* Add / Edit preset form */}
        {showAddPreset && (
          <div className="mt-4 bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-slate-200 uppercase tracking-wide">
                {editingPresetId ? `Edit preset: ${editingPresetId}` : "New transcription preset"}
              </p>
            </div>

            {/* Preset Name */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Preset Name</label>
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Name (e.g. Whisper Medium, VibeVoice 7B, Qwen3 1.7B)"
                className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              />
            </div>

            {/* Engine Selection */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Engine</label>
              <select
                value={newEngine}
                onChange={(e) => handleEngineChange(e.target.value)}
                className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              >
                {settings.engines.map((e) => {
                  const meta = engineMeta(e);
                  return (
                    <option key={e} value={e}>
                      {e} — {meta.label}
                    </option>
                  );
                })}
              </select>
            </div>

            {/* Engine Description Banner */}
            {currentEngineMeta.description && (
              <div className={`p-2.5 rounded-lg border text-xs ${currentEngineMeta.badgeStyle}`}>
                <div className="font-semibold flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${currentEngineMeta.badgeDot}`} />
                  {currentEngineMeta.label} ({currentEngineMeta.badgeText})
                </div>
                <p className="text-[11px] mt-1 opacity-90">
                  {currentEngineMeta.description}
                </p>
              </div>
            )}

            {/* Model Path */}
            <div>
              <label className="block text-xs text-slate-400 mb-1">Model Path / Identifier</label>
              <input
                value={newModelPath}
                onChange={(e) => setNewModelPath(e.target.value)}
                placeholder={currentEngineMeta.modelPlaceholder}
                className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-violet-500/50"
              />
            </div>

            {/* Forced Aligner Path */}
            {currentEngineMeta.supportsAligner && (
              <div>
                <label className="block text-xs text-slate-400 mb-1">Forced Aligner Path (optional)</label>
                <input
                  value={newAlignerPath}
                  onChange={(e) => setNewAlignerPath(e.target.value)}
                  placeholder={currentEngineMeta.alignerPlaceholder || "Path to alignment model"}
                  className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                />
              </div>
            )}

            {/* Language, Device, and Decoder Row */}
            <div className="grid grid-cols-2 gap-3">
              {currentEngineMeta.supportsLanguage && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Language</label>
                  <input
                    value={newLanguage}
                    onChange={(e) => setNewLanguage(e.target.value)}
                    placeholder="Language code or name (e.g. pt, Portuguese)"
                    className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                  />
                </div>
              )}

              {currentEngineMeta.supportsDevice && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Device</label>
                  <select
                    value={newDevice}
                    onChange={(e) => setNewDevice(e.target.value)}
                    className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                  >
                    <option value="cuda">cuda (GPU)</option>
                    <option value="cpu">cpu</option>
                    <option value="auto">auto</option>
                  </select>
                </div>
              )}

              {currentEngineMeta.supportsDecoder && (
                <div>
                  <label className="block text-xs text-slate-400 mb-1">Decoder</label>
                  <select
                    value={newDecoder}
                    onChange={(e) => setNewDecoder(e.target.value)}
                    className="w-full bg-slate-900/80 border border-slate-700/60 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                  >
                    <option value="tdt">tdt</option>
                    <option value="ctc">ctc</option>
                  </select>
                </div>
              )}
            </div>

            {addError && <p className="text-xs text-red-400">{addError}</p>}

            <div className="flex gap-2 justify-end pt-1">
              <button
                type="button"
                onClick={cancelPresetForm}
                className="px-3.5 py-1.5 text-xs text-slate-400 hover:text-white transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSavePreset}
                className="px-4 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition font-medium shadow-sm shadow-violet-500/20"
              >
                {editingPresetId ? "Update preset" : "Add preset"}
              </button>
            </div>
          </div>
        )}
      </div>

    </>
  );
}
