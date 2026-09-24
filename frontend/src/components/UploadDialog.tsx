import { useEffect, useRef, useState } from "react";
import { createMeeting, getModelSettings, listVocabularyProfiles, createVocabularyProfile } from "../api";
import type { ModelSettings, VocabularyProfile } from "../types";
import { formatVocabulary, cleanParticipants } from "../utils/vocabulary";
import { firstUsablePreset } from "../utils/engineHealth";

interface Props {
  onClose: () => void;
  onCreated: (meetingId: string) => void;
}

/** The "New transcription" dialog. Mounted only while open, so closing it resets every field. */
export default function UploadDialog({ onClose, onCreated }: Props) {
  const [uploading, setUploading] = useState(false);
  const [title, setTitle] = useState("");
  const [participants, setParticipants] = useState("");
  const [minSpeakers, setMinSpeakers] = useState("");
  const [maxSpeakers, setMaxSpeakers] = useState("");
  const [vocabulary, setVocabulary] = useState("");
  const [profiles, setProfiles] = useState<VocabularyProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [presetId, setPresetId] = useState("");
  const [modelSettings, setModelSettings] = useState<ModelSettings | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const micFileRef = useRef<HTMLInputElement>(null);
  const systemFileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dualTrackMode, setDualTrackMode] = useState(false);
  const [micFile, setMicFile] = useState<File | null>(null);
  const [systemFile, setSystemFile] = useState<File | null>(null);

  // Error feedback
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadModelSettings();
    loadProfiles();
  }, []);

  async function loadModelSettings() {
    try {
      const data = await getModelSettings();
      setModelSettings(data);
      const defaultPreset = data.presets.find((p) => p.id === data.default_preset);
      if (defaultPreset?.state === "blocked") {
        setPresetId(firstUsablePreset(data.presets)?.id || "");
      }
    } catch {
      setModelSettings(null);
    }
  }

  async function loadProfiles() {
    try {
      const data = await listVocabularyProfiles();
      setProfiles(data);
    } catch {
      setProfiles([]);
    }
  }

  async function handleUpload() {
    if (!title.trim()) return;
    const primary = dualTrackMode ? micFile : selectedFile;
    if (!primary) return;
    const secondary = dualTrackMode ? systemFile : null;

    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", primary);
      if (secondary) form.append("system_file", secondary);
      form.append("title", title.trim());
      if (minSpeakers) form.append("min_speakers", minSpeakers);
      if (maxSpeakers) form.append("max_speakers", maxSpeakers);
      const formattedVocab = formatVocabulary(cleanParticipants(participants), vocabulary);
      if (formattedVocab) form.append("vocabulary", formattedVocab);
      const cleanedParticipants = cleanParticipants(participants).join(", ");
      if (cleanedParticipants) form.append("participants", cleanedParticipants);
      if (presetId) form.append("preset_id", presetId);

      const meeting = await createMeeting(form);
      onCreated(meeting.id);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const msg = detail?.message || detail || err?.message || "Upload failed";
      setError(msg);
    } finally {
      setUploading(false);
    }
  }

  function handleProfileSelect(id: string) {
    setProfileId(id);
    const profile = profiles.find((p) => p.id === id);
    if (profile) {
      setVocabulary(profile.terms);
    }
  }

  async function handleSaveProfile() {
    const name = profileName.trim();
    const terms = vocabulary.trim();
    if (!name || !terms) return;
    setSavingProfile(true);
    try {
      await createVocabularyProfile(name, terms);
      setProfileName("");
      await loadProfiles();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to save profile");
    } finally {
      setSavingProfile(false);
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) {
      setSelectedFile(file);
      if (!title) setTitle(file.name.replace(/\.[^/.]+$/, ""));
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700/50 rounded-2xl shadow-2xl p-6 w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-xl font-bold text-white mb-5">New transcription</h2>

        {/* Mode toggle: single file vs dual-track */}
        <div className="flex gap-2 mb-5">
          <button
            onClick={() => setDualTrackMode(false)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition ${
              !dualTrackMode
                ? "bg-violet-600 text-white"
                : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            Single file
          </button>
          <button
            onClick={() => setDualTrackMode(true)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition ${
              dualTrackMode
                ? "bg-violet-600 text-white"
                : "bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700"
            }`}
          >
            Dual-track / OBS
          </button>
        </div>

        {dualTrackMode ? (
          <div className="space-y-3 mb-5">
            {/* Mic track (required) */}
            <div
              className={`relative border-2 border-dashed rounded-xl p-5 text-center transition-all cursor-pointer group ${
                micFile
                  ? "border-emerald-500/50 bg-emerald-500/5"
                  : "border-slate-700 hover:border-slate-500 hover:bg-slate-800/50"
              }`}
              onClick={() => micFileRef.current?.click()}
            >
              <input
                ref={micFileRef}
                type="file"
                accept="audio/*,video/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) {
                    setMicFile(f);
                    if (!title) setTitle(f.name.replace(/\.[^/.]+$/, ""));
                  }
                }}
              />
              {micFile ? (
                <div>
                  <p className="text-xs text-slate-500 mb-1">Microphone track</p>
                  <p className="text-white font-medium">{micFile.name}</p>
                  <p className="text-slate-500 text-sm mt-1">{(micFile.size / 1024 / 1024).toFixed(1)} MB</p>
                </div>
              ) : (
                <div>
                  <p className="text-slate-300 font-medium">Microphone track</p>
                  <p className="text-slate-500 text-sm mt-1">Drop or click — a stereo file is split into mic + system</p>
                </div>
              )}
            </div>
            {/* System track (optional) */}
            <div
              className={`relative border-2 border-dashed rounded-xl p-5 text-center transition-all cursor-pointer group ${
                systemFile
                  ? "border-emerald-500/50 bg-emerald-500/5"
                  : "border-slate-700 hover:border-slate-500 hover:bg-slate-800/50"
              }`}
              onClick={() => systemFileRef.current?.click()}
            >
              <input
                ref={systemFileRef}
                type="file"
                accept="audio/*,video/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) setSystemFile(f);
                }}
              />
              {systemFile ? (
                <div>
                  <p className="text-xs text-slate-500 mb-1">System audio track</p>
                  <p className="text-white font-medium">{systemFile.name}</p>
                  <p className="text-slate-500 text-sm mt-1">{(systemFile.size / 1024 / 1024).toFixed(1)} MB</p>
                  <button
                    onClick={(e) => { e.stopPropagation(); setSystemFile(null); }}
                    className="mt-2 text-xs text-slate-500 hover:text-red-400 transition"
                  >
                    Remove
                  </button>
                </div>
              ) : (
                <div>
                  <p className="text-slate-300 font-medium">System audio track (optional)</p>
                  <p className="text-slate-500 text-sm mt-1">Meeting / desktop audio. Leave empty to split a stereo mic file.</p>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div
            className={`relative border-2 border-dashed rounded-xl p-8 text-center mb-5 transition-all cursor-pointer group ${
              dragOver
                ? "border-violet-500 bg-violet-500/10"
                : selectedFile
                ? "border-emerald-500/50 bg-emerald-500/5"
                : "border-slate-700 hover:border-slate-500 hover:bg-slate-800/50"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept="audio/*,video/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setSelectedFile(f);
                  if (!title) setTitle(f.name.replace(/\.[^/.]+$/, ""));
                }
              }}
            />
            {selectedFile ? (
              <div>
                <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-emerald-500/20 flex items-center justify-center">
                  <svg className="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-white font-medium">{selectedFile.name}</p>
                <p className="text-slate-500 text-sm mt-1">{(selectedFile.size / 1024 / 1024).toFixed(1)} MB</p>
              </div>
            ) : (
              <div>
                <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-slate-800 flex items-center justify-center group-hover:bg-slate-700 transition">
                  <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                </div>
                <p className="text-slate-300 font-medium">Drag and drop a file here</p>
                <p className="text-slate-500 text-sm mt-1">or click to browse</p>
                <p className="text-slate-600 text-xs mt-2">MP3, WAV, MP4, M4A, WEBM</p>
              </div>
            )}
          </div>
        )}

        {/* Title */}
        <input
          type="text"
          placeholder="Title for the transcription"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500/50 mb-4"
        />

        {/* Preset */}
        <div className="mb-4">
          <label className="block text-xs text-slate-500 mb-1.5">
            Preset
          </label>
          <select
            value={presetId}
            onChange={(e) => setPresetId(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
          >
            <option value="" disabled={modelSettings?.presets.find((p) => p.id === modelSettings.default_preset)?.state === "blocked"}>
              Default{modelSettings ? ` (${modelSettings.presets.find((p) => p.id === modelSettings.default_preset)?.name || modelSettings.default_preset})` : ""}
            </option>
            {modelSettings?.presets.map((p) => (
              <option key={p.id} value={p.id} disabled={p.state === "blocked"} title={p.state === "ready" ? undefined : p.summary}>
                {p.name} — {p.engine}
                {p.state === "blocked" ? " (blocked)" : p.state === "degraded" ? " (degraded)" : ""}
              </option>
            ))}
          </select>
          {(() => {
            const selectedPreset = modelSettings?.presets.find((p) => p.id === (presetId || modelSettings.default_preset));
            return selectedPreset?.state === "degraded" ? (
              <p className="text-xs text-amber-400 mt-1.5">{selectedPreset.summary}</p>
            ) : null;
          })()}
          <p className="text-xs text-slate-600 mt-1.5">
            Choose which Engine transcribes this file. Useful for comparing results across Presets.
          </p>
        </div>

        {/* Participants */}
        <div className="mb-4">
          <label className="block text-xs text-slate-500 mb-1.5">
            Meeting Participants / Attendees
          </label>
          <textarea
            value={participants}
            onChange={(e) => setParticipants(e.target.value)}
            placeholder="Paste names from Google Meet, Zoom, Teams, or call chat (one per line or separated by commas)"
            className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm resize-none"
            rows={3}
            maxLength={2000}
          />
          <p className="text-xs text-slate-600 mt-1.5">
            Names are cleaned automatically (emails, timestamps, status markers stripped).
          </p>
        </div>

        {/* Domain Terms */}
        <div className="mb-4">
          <label className="block text-xs text-slate-500 mb-1.5">
            Domain Terms &amp; Jargon
          </label>
          <textarea
            value={vocabulary}
            onChange={(e) => setVocabulary(e.target.value)}
            placeholder="Technical terms, acronyms, product names, or project keywords"
            className="w-full bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50 text-sm resize-none"
            rows={2}
            maxLength={2000}
          />
          {/* Profile selector */}
          <div className="flex items-center gap-2 mt-2">
            <select
              value={profileId}
              onChange={(e) => handleProfileSelect(e.target.value)}
              className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-1.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-violet-500/50"
            >
              <option value="">Load a vocabulary profile...</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
            <button
              onClick={handleSaveProfile}
              disabled={savingProfile || !vocabulary.trim() || !profileName.trim()}
              className="px-3 py-1.5 text-xs text-violet-400 hover:text-violet-300 transition flex items-center gap-1 font-medium disabled:opacity-40"
            >
              {savingProfile ? "Saving..." : "Save as profile"}
            </button>
          </div>
          {profiles.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {profiles.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleProfileSelect(p.id)}
                  className={`px-2.5 py-1 rounded-full text-xs font-medium transition border ${
                    profileId === p.id
                      ? "bg-violet-500/20 text-violet-300 border-violet-500/40"
                      : "bg-slate-800 text-slate-400 border-slate-700/50 hover:text-white hover:border-slate-600"
                  }`}
                >
                  {p.name}
                </button>
              ))}
            </div>
          )}
          {/* Save-as-profile name input */}
          <div className="flex items-center gap-2 mt-2">
            <input
              type="text"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              placeholder="Profile name (e.g. Dev / Engineering)"
              className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
            />
            <button
              onClick={handleSaveProfile}
              disabled={savingProfile || !vocabulary.trim() || !profileName.trim()}
              className="px-3 py-1.5 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg font-medium transition disabled:opacity-40"
            >
              {savingProfile ? "Saving..." : "Save"}
            </button>
          </div>
        </div>

        {/* Advanced settings */}
        <details className="mb-5 group">
          <summary className="text-sm text-slate-500 cursor-pointer hover:text-slate-300 transition">
            Advanced settings
          </summary>
          <div className="mt-3 space-y-3">
            <div className="flex gap-3">
              <input
                type="number"
                placeholder="Min speakers"
                value={minSpeakers}
                onChange={(e) => setMinSpeakers(e.target.value)}
                className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                min="1"
              />
              <input
                type="number"
                placeholder="Max speakers"
                value={maxSpeakers}
                onChange={(e) => setMaxSpeakers(e.target.value)}
                className="flex-1 bg-slate-800 border border-slate-700/50 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-violet-500/50"
                min="1"
              />
            </div>

          </div>
        </details>

        {/* Error message */}
        {error && (
          <div className="mb-4 px-4 py-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm flex items-start gap-2">
            <svg className="w-4 h-4 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-5 py-2.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl transition"
          >
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={uploading || (dualTrackMode ? !micFile : !selectedFile) || !title.trim()}
            className="px-5 py-2.5 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-medium hover:from-violet-500 hover:to-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-violet-500/25"
          >
            {uploading ? (
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Uploading...
              </span>
            ) : (
              "Start transcription"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
