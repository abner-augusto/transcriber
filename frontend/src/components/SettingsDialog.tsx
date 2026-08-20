import { useEffect, useState } from "react";
import type { ModelSettings } from "../types";
import {
  getModelSettings, createModelPreset, deleteModelPreset, setDefaultPreset,
  getPreferences, updatePreferences, listSpeakerProfiles, deleteSpeakerProfile,
  listVocabulary, deleteVocabularyEntry,
} from "../api";
import type { Preferences, SpeakerProfile, VocabularyEntry } from "../api";

interface Props {
  onClose: () => void;
}

export default function SettingsDialog({ onClose }: Props) {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [tab, setTab] = useState<"presets" | "preferences">("presets");

  // Add-preset form
  const [showAddPreset, setShowAddPreset] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEngine, setNewEngine] = useState("whisper.cpp");
  const [newModelPath, setNewModelPath] = useState("");
  const [newLanguage, setNewLanguage] = useState("");
  const [newDecoder, setNewDecoder] = useState("tdt");
  const [addError, setAddError] = useState("");
  const [defaultSaving, setDefaultSaving] = useState<string | null>(null);

  // Preferences
  const [defaultVocab, setDefaultVocab] = useState("");
  const [profilesEnabled, setProfilesEnabled] = useState(true);
  const [hfToken, setHfToken] = useState("");
  const [profiles, setProfiles] = useState<SpeakerProfile[]>([]);
  const [learnedVocab, setLearnedVocab] = useState<VocabularyEntry[]>([]);

  useEffect(() => {
    loadSettings();
    loadPreferences();
  }, []);

  async function loadSettings() {
    const data = await getModelSettings();
    setSettings(data);
    if (data.engines.length > 0) setNewEngine(data.engines[0]);
  }

  async function loadPreferences() {
    const p = await getPreferences();
    setDefaultVocab(p.default_vocabulary || "");
    setProfilesEnabled(p.speaker_profiles_enabled);
    setHfToken(p.hf_auth_token || "");
    setProfiles(await listSpeakerProfiles());
    setLearnedVocab(await listVocabulary());
  }

  async function handleSave() {
    setSaving(true);
    if (tab === "preferences") {
      await updatePreferences({
        default_vocabulary: defaultVocab,
        speaker_profiles_enabled: profilesEnabled,
        hf_auth_token: hfToken,
      });
    }
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  async function handleAddPreset() {
    if (!newName.trim() || !newModelPath.trim()) {
      setAddError("Name and model path are required.");
      return;
    }
    setAddError("");
    try {
      await createModelPreset({
        name: newName.trim(),
        engine: newEngine,
        model_path: newModelPath.trim(),
        language: (newEngine === "whisper.cpp" || newEngine === "faster-whisper") && newLanguage.trim() ? newLanguage.trim() : undefined,
        decoder: newEngine === "parakeet.cpp" ? newDecoder : undefined,
      });
      setNewName(""); setNewModelPath(""); setNewLanguage(""); setNewDecoder("tdt");
      setShowAddPreset(false);
      const data = await getModelSettings();
      setSettings(data);
    } catch (err: any) {
      setAddError(err?.response?.data?.detail || "Failed to create preset");
    }
  }

  async function handleDeletePreset(id: string) {
    const preset = settings?.presets.find((p) => p.id === id);
    if (!confirm(`Delete preset "${preset?.name}"?`)) return;
    try {
      await deleteModelPreset(id);
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
      alert(err?.response?.data?.detail || "Failed to set default preset");
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
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
        <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-white mb-4">Settings</h2>

        <div className="flex bg-slate-800 rounded-xl p-1 mb-5">
          {(["presets", "preferences"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all capitalize ${tab === t ? "bg-slate-700 text-white shadow-sm" : "text-slate-400 hover:text-white"}`}>
              {t}
            </button>
          ))}
        </div>

        {tab === "presets" ? (
          <div className="space-y-5 max-h-[60vh] overflow-y-auto pr-1">

            {/* Transcription presets list */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Transcription Presets</p>
                <button onClick={() => setShowAddPreset(!showAddPreset)}
                  className="text-xs text-violet-400 hover:text-violet-300 transition flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                  </svg>
                  Add
                </button>
              </div>

              <div className="space-y-1.5">
                {settings.presets.map((p) => (
                  <div key={p.id}
                    className="flex items-center justify-between bg-slate-800/30 rounded-lg px-3 py-2 gap-3">
                    <label className="flex items-center gap-2.5 min-w-0 flex-1 cursor-pointer" title={p.available ? undefined : p.reason || "Unavailable"}>
                      <input
                        type="radio"
                        name="default-preset"
                        checked={settings.default_preset === p.id}
                        disabled={!p.available || defaultSaving === p.id}
                        onChange={() => handleSetDefault(p.id)}
                        className="accent-violet-600"
                      />
                      <span
                        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${p.available ? "bg-emerald-400" : "bg-red-400"}`}
                      />
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-sm text-slate-200 truncate">{p.name}</span>
                          <span className="text-[10px] text-slate-500 uppercase tracking-wide flex-shrink-0">{p.engine}</span>
                          {settings.default_preset === p.id && (
                            <span className="text-[10px] text-violet-400 flex-shrink-0">default</span>
                          )}
                        </div>
                        <span className="text-xs text-slate-500 font-mono truncate block">{p.model_path}</span>
                      </div>
                    </label>
                    <button onClick={() => handleDeletePreset(p.id)}
                      className="text-slate-600 hover:text-red-400 transition p-1 flex-shrink-0">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                ))}
                {settings.presets.length === 0 && (
                  <p className="text-xs text-slate-600">No presets configured yet.</p>
                )}
              </div>
              <p className="text-[10px] text-slate-600 mt-1.5">
                Select the radio to make a preset the default. Unavailable presets are missing their engine binary or model file.
              </p>

              {showAddPreset && (
                <div className="mt-3 bg-slate-800/50 rounded-xl p-3 space-y-2">
                  <p className="text-xs font-medium text-slate-300">New preset</p>
                  <input value={newName} onChange={(e) => setNewName(e.target.value)}
                    placeholder="Name (e.g. Whisper Medium)"
                    className="w-full bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50" />
                  <select value={newEngine} onChange={(e) => setNewEngine(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50">
                    {settings.engines.map((e) => (
                      <option key={e} value={e}>{e}</option>
                    ))}
                  </select>
                  <input value={newModelPath} onChange={(e) => setNewModelPath(e.target.value)}
                    placeholder={newEngine === "faster-whisper" ? "Model (e.g. large-v3-turbo, inesc-id/WhisperLv3-X-PT-All)" : "Model path (e.g. ./models/ggml-medium.bin)"}
                    className="w-full bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-violet-500/50" />
                  {(newEngine === "whisper.cpp" || newEngine === "faster-whisper") && (
                    <input value={newLanguage} onChange={(e) => setNewLanguage(e.target.value)}
                      placeholder="Language code (optional, e.g. pt)"
                      className="w-full bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50" />
                  )}
                  {newEngine === "parakeet.cpp" && (
                    <select value={newDecoder} onChange={(e) => setNewDecoder(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50">
                      <option value="tdt">tdt</option>
                      <option value="ctc">ctc</option>
                    </select>
                  )}
                  {addError && <p className="text-xs text-red-400">{addError}</p>}
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => { setShowAddPreset(false); setAddError(""); }}
                      className="px-3 py-1.5 text-xs text-slate-400 hover:text-white transition">Cancel</button>
                    <button onClick={handleAddPreset}
                      className="px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg transition">Add</button>
                  </div>
                </div>
              )}
            </div>

          </div>
        ) : (
          <div className="space-y-5 max-h-[60vh] overflow-y-auto pr-1">

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
