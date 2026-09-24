import { deleteVocabularyEntry } from "../../api";
import type { PreferencesForm } from "./usePreferencesForm";

interface Props {
  form: PreferencesForm;
}

export default function PreferencesTab({ form }: Props) {
  const {
    defaultVocab, setDefaultVocab, profilesEnabled, setProfilesEnabled,
    hfToken, setHfToken, clusterThreshold, setClusterThreshold,
    switchPenalty, setSwitchPenalty, profiles, learnedVocab, setLearnedVocab,
    vocabProfiles, newProfileName, setNewProfileName, newProfileTerms, setNewProfileTerms,
    savingVocabProfile, handleCreateVocabProfile, handleDeleteVocabProfile, handleDeleteProfile,
  } = form;

  return (
    <>

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

    </>
  );
}
