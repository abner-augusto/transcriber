import { useEffect, useState } from "react";
import type { ModelSettings, Preset } from "../types";
import {
  getModelSettings, createModelPreset, updateModelPreset, deleteModelPreset, setDefaultPreset,
  getPreferences, updatePreferences, listSpeakerProfiles, deleteSpeakerProfile,
  listVocabulary, deleteVocabularyEntry,
  listVocabularyProfiles, createVocabularyProfile, deleteVocabularyProfile,
} from "../api";
import type { SpeakerProfile, VocabularyEntry } from "../api";
import type { VocabularyProfile } from "../types";
import { engineMeta } from "../engineMetadata";

interface Props {
  onClose: () => void;
}

export default function SettingsDialog({ onClose }: Props) {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [tab, setTab] = useState<"presets" | "preferences">("presets");

  // Preset form (Add / Edit)
  const [showAddPreset, setShowAddPreset] = useState(false);
  const [editingPresetId, setEditingPresetId] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [newEngine, setNewEngine] = useState("vibevoice");
  const [newModelPath, setNewModelPath] = useState("");
  const [newAlignerPath, setNewAlignerPath] = useState("");
  const [newLanguage, setNewLanguage] = useState("");
  const [newDecoder, setNewDecoder] = useState("tdt");
  const [newDevice, setNewDevice] = useState("cuda");
  const [addError, setAddError] = useState("");
  const [defaultSaving, setDefaultSaving] = useState<string | null>(null);

  // Preferences
  const [defaultVocab, setDefaultVocab] = useState("");
  const [profilesEnabled, setProfilesEnabled] = useState(true);
  const [hfToken, setHfToken] = useState("");
  const [clusterThreshold, setClusterThreshold] = useState<number | null>(null);
  const [switchPenalty, setSwitchPenalty] = useState(0.8);
  const [profiles, setProfiles] = useState<SpeakerProfile[]>([]);
  const [learnedVocab, setLearnedVocab] = useState<VocabularyEntry[]>([]);
  const [vocabProfiles, setVocabProfiles] = useState<VocabularyProfile[]>([]);
  const [newProfileName, setNewProfileName] = useState("");
  const [newProfileTerms, setNewProfileTerms] = useState("");
  const [savingVocabProfile, setSavingVocabProfile] = useState(false);

  useEffect(() => {
    loadSettings();
    loadPreferences();
  }, []);

  async function loadSettings() {
    const data = await getModelSettings();
    setSettings(data);
    if (data.engines.length > 0 && !editingPresetId) {
      const initialEngine = data.engines.includes("vibevoice")
        ? "vibevoice"
        : data.engines.includes("qwen3-asr")
        ? "qwen3-asr"
        : data.engines[0];
      setNewEngine(initialEngine);
      applyEngineDefaults(initialEngine);
    }
  }

  function applyEngineDefaults(engine: string) {
    const meta = engineMeta(engine);
    setNewDevice(meta.defaultDevice || "cuda");
    setNewLanguage(meta.defaultLanguage || "");
    if (engine === "parakeet.cpp") setNewDecoder("tdt");
  }

  function handleEngineChange(engine: string) {
    setNewEngine(engine);
    setAddError("");
    applyEngineDefaults(engine);
  }

  function resetPresetForm() {
    setEditingPresetId(null);
    setNewName("");
    setNewModelPath("");
    setNewAlignerPath("");
    setNewLanguage("");
    setNewDecoder("tdt");
    setNewDevice("cuda");
    setAddError("");
  }

  function startEditPreset(preset: Preset) {
    setEditingPresetId(preset.id);
    setNewName(preset.name);
    setNewEngine(preset.engine);
    setNewModelPath(preset.model_path);
    setNewAlignerPath(preset.aligner_path || "");
    setNewLanguage(preset.language || "");
    setNewDecoder(preset.decoder || "tdt");
    setNewDevice(preset.device || "cuda");
    setAddError("");
    setShowAddPreset(true);
  }

  function cancelPresetForm() {
    setShowAddPreset(false);
    resetPresetForm();
  }

  async function loadPreferences() {
    const p = await getPreferences();
    setDefaultVocab(p.default_vocabulary || "");
    setProfilesEnabled(p.speaker_profiles_enabled);
    setHfToken(p.hf_auth_token || "");
    setClusterThreshold(p.diarization?.clustering_threshold ?? null);
    setSwitchPenalty(p.speaker_switch_penalty ?? 0.8);
    setProfiles(await listSpeakerProfiles());
    setLearnedVocab(await listVocabulary());
    setVocabProfiles(await listVocabularyProfiles());
  }

  async function handleCreateVocabProfile() {
    const name = newProfileName.trim();
    const terms = newProfileTerms.trim();
    if (!name || !terms) return;
    setSavingVocabProfile(true);
    try {
      await createVocabularyProfile(name, terms);
      setNewProfileName("");
      setNewProfileTerms("");
      setVocabProfiles(await listVocabularyProfiles());
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to create profile");
    } finally {
      setSavingVocabProfile(false);
    }
  }

  async function handleDeleteVocabProfile(id: string) {
    const profile = vocabProfiles.find((p) => p.id === id);
    if (!confirm(`Delete vocabulary profile "${profile?.name}"?`)) return;
    await deleteVocabularyProfile(id);
    setVocabProfiles(vocabProfiles.filter((p) => p.id !== id));
  }

  async function handleSave() {
    setSaving(true);
    if (tab === "preferences") {
      await updatePreferences({
        default_vocabulary: defaultVocab,
        speaker_profiles_enabled: profilesEnabled,
        hf_auth_token: hfToken,
        speaker_switch_penalty: switchPenalty,
        diarization: clusterThreshold == null ? {} : { clustering_threshold: clusterThreshold },
      });
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleSavePreset() {
    const trimmedName = newName.trim();
    const trimmedModelPath = newModelPath.trim();

    if (!trimmedName || !trimmedModelPath) {
      setAddError("Preset name and model path are required.");
      return;
    }
    setAddError("");

    const meta = engineMeta(newEngine);

    const payload = {
      name: trimmedName,
      engine: newEngine,
      model_path: trimmedModelPath,
      aligner_path: meta.supportsAligner && newAlignerPath.trim() ? newAlignerPath.trim() : undefined,
      language: meta.supportsLanguage && newLanguage.trim() ? newLanguage.trim() : undefined,
      device: meta.supportsDevice && newDevice.trim() ? newDevice.trim() : undefined,
      decoder: meta.supportsDecoder ? newDecoder : undefined,
    };

    try {
      if (editingPresetId) {
        await updateModelPreset(editingPresetId, payload);
      } else {
        await createModelPreset(payload);
      }
      cancelPresetForm();
      const data = await getModelSettings();
      setSettings(data);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setAddError(detail?.message || detail || "Failed to save preset");
    }
  }

  async function handleDeletePreset(id: string) {
    const preset = settings?.presets.find((p) => p.id === id);
    if (!confirm(`Delete preset "${preset?.name}"?`)) return;
    try {
      await deleteModelPreset(id);
      if (editingPresetId === id) cancelPresetForm();
      const data = await getModelSettings();
      setSettings(data);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to delete preset");
    }
  }

  async function handleSetDefault(id: string) {
    if (!settings || settings.default_preset === id) return;
    setDefaultSaving(id);
    try {
      const { default_preset } = await setDefaultPreset(id);
      setSettings({ ...settings, default_preset });
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      alert(detail?.message || detail || "Failed to set default preset");
    } finally {
      setDefaultSaving(null);
    }
  }

  async function handleDeleteProfile(id: string) {
    const profile = profiles.find((p) => p.id === id);
    if (!confirm(`Delete voice profile "${profile?.name}"?`)) return;
    await deleteSpeakerProfile(id);
    setProfiles(profiles.filter((p) => p.id !== id));
  }

  if (!settings) {
    return (
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
        <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-2xl" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
          </div>
        </div>
      </div>
    );
  }

  const currentEngineMeta = engineMeta(newEngine);

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-2xl max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-white mb-4 flex-shrink-0">Settings</h2>

        <div className="flex bg-slate-800 rounded-xl p-1 mb-5 flex-shrink-0">
          {(["presets", "preferences"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all capitalize ${tab === t ? "bg-slate-700 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}>
              {t}
            </button>
          ))}
        </div>

        {tab === "presets" ? (
          <div className="space-y-5 overflow-y-auto pr-1 flex-1">

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
                          className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                            p.state === "ready" ? "bg-emerald-400 ring-2 ring-emerald-400/20" : p.state === "degraded" ? "bg-amber-400 ring-2 ring-amber-400/20" : "bg-red-400 ring-2 ring-red-400/20"
                          }`}
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

          </div>
        ) : (
          <div className="space-y-5 overflow-y-auto pr-1 flex-1">

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Hugging Face token</label>
              <p className="text-xs text-slate-500 mb-1.5">
                Required for speaker diarization.{" "}
                <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer"
                  className="text-violet-400 hover:text-violet-300">huggingface.co/settings/tokens</a>
              </p>
              <input type="password" value={hfToken} onChange={(e) => setHfToken(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                placeholder="hf_..." autoComplete="off" />
            </div>

            <div className="border-t border-slate-800" />

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
                <span className="text-xs text-slate-400 font-mono w-10 text-right">
                  {switchPenalty.toFixed(2)}
                </span>
              </div>
              <div className="flex text-[10px] text-slate-600 mt-1">
                <span>more responsive</span>
                <span className="flex-1" />
                <span>more stable</span>
              </div>
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
                <span>more speakers</span>
                <span className="flex-1" />
                <span>fewer speakers</span>
              </div>
              <label className="flex items-center gap-2 mt-2 text-xs text-slate-400 cursor-pointer">
                <input type="checkbox" checked={clusterThreshold == null}
                  onChange={(e) => setClusterThreshold(e.target.checked ? null : 0.7)}
                  className="accent-violet-600" />
                Use model default
              </label>
            </div>

            <div className="border-t border-slate-800" />

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Default vocabulary</label>
              <p className="text-xs text-slate-500 mb-1.5">Domain-specific terms applied to all new transcriptions.</p>
              <textarea value={defaultVocab} onChange={(e) => setDefaultVocab(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50 resize-none"
                rows={3} maxLength={2000} placeholder="Names, technical terms, abbreviations..." />
            </div>

            {learnedVocab.length > 0 && (
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Learned vocabulary</label>
                <p className="text-xs text-slate-500 mb-1.5">Terms automatically learned from transcript corrections.</p>
                <div className="flex flex-wrap gap-1.5">
                  {learnedVocab.map((v) => (
                    <span key={v.id}
                      className="inline-flex items-center gap-1 bg-slate-800/50 rounded-md px-2 py-1 text-xs text-slate-300 group">
                      {v.term}
                      <span className="text-[9px] text-slate-600">{v.frequency}x</span>
                      <button onClick={async () => { await deleteVocabularyEntry(v.id); setLearnedVocab(learnedVocab.filter((e) => e.id !== v.id)); }}
                        className="opacity-0 group-hover:opacity-100 text-slate-600 hover:text-red-400 transition ml-0.5">
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Vocabulary Profiles */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-slate-300">Vocabulary Profiles</label>
                <button
                  onClick={() => setNewProfileName("")}
                  className="text-xs text-violet-400 hover:text-violet-300 transition flex items-center gap-1 font-medium"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add profile
                </button>
              </div>
              <p className="text-xs text-slate-500 mb-2">Reusable term presets for quick loading in the upload dialog.</p>

              {/* Existing profiles */}
              {vocabProfiles.length > 0 && (
                <div className="space-y-1.5 mb-3">
                  {vocabProfiles.map((p) => (
                    <div key={p.id} className="flex items-center justify-between bg-slate-800/50 rounded-lg px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <span className="text-sm text-slate-300">{p.name}</span>
                        <p className="text-[10px] text-slate-500 truncate mt-0.5">{p.terms}</p>
                      </div>
                      <button onClick={() => handleDeleteVocabProfile(p.id)}
                        className="text-slate-600 hover:text-red-400 transition p-1 flex-shrink-0">
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Create new profile form */}
              <div className="space-y-2">
                <input
                  type="text"
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                  placeholder="Profile name (e.g. Dev / Engineering)"
                  className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                />
                <textarea
                  value={newProfileTerms}
                  onChange={(e) => setNewProfileTerms(e.target.value)}
                  placeholder="Terms (comma-separated: Docker, Kubernetes, gRPC, Celery...)"
                  className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 resize-none"
                  rows={2}
                  maxLength={2000}
                />
                <button
                  onClick={handleCreateVocabProfile}
                  disabled={savingVocabProfile || !newProfileName.trim() || !newProfileTerms.trim()}
                  className="px-4 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg font-medium transition disabled:opacity-40"
                >
                  {savingVocabProfile ? "Saving..." : "Create profile"}
                </button>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-sm font-medium text-slate-300">Speaker voice profiles</label>
                  <p className="text-xs text-slate-500 mt-0.5">Save and match voice profiles across meetings.</p>
                </div>
                <button onClick={() => setProfilesEnabled(!profilesEnabled)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${profilesEnabled ? "bg-violet-600" : "bg-slate-700"}`}>
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${profilesEnabled ? "translate-x-6" : "translate-x-1"}`} />
                </button>
              </div>
              {profiles.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  <p className="text-xs text-slate-500">{profiles.length} saved voice profile(s)</p>
                  {profiles.map((p) => (
                    <div key={p.id} className="flex items-center justify-between bg-slate-800/50 rounded-lg px-3 py-2">
                      <div>
                        <span className="text-sm text-slate-300">{p.name}</span>
                        <span className="text-[10px] text-slate-600 ml-2">{p.sample_count} sample(s)</span>
                      </div>
                      <button onClick={() => handleDeleteProfile(p.id)}
                        className="text-slate-600 hover:text-red-400 transition p-1">
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

          </div>
        )}

        <div className="flex items-center justify-end gap-3 mt-6">
          <button onClick={onClose}
            className="px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition text-sm">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="px-5 py-2 bg-violet-600 text-white rounded-xl font-medium hover:bg-violet-500 disabled:opacity-50 transition text-sm flex items-center gap-2">
            {saving ? (<><div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />Saving...</>) : saved ? "Saved!" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
