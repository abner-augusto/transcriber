import { useEffect, useState } from "react";
import {
  getPreferences, updatePreferences, listSpeakerProfiles, deleteSpeakerProfile,
  listVocabulary, listVocabularyProfiles, createVocabularyProfile, deleteVocabularyProfile,
} from "../../api";
import type { SpeakerProfile, VocabularyEntry } from "../../api";
import type { VocabularyProfile } from "../../types";

/**
 * The Preferences tab's fields, loaded once when the Settings dialog opens.
 *
 * Owned by the dialog, not the tab, so unsaved edits survive switching tabs and the
 * dialog's shared Save button can write them.
 */
export function usePreferencesForm() {
  const [defaultVocab, setDefaultVocab] = useState("");
  const [voiceProfilesEnabled, setVoiceProfilesEnabled] = useState(true);
  const [hfToken, setHfToken] = useState("");
  const [clusterThreshold, setClusterThreshold] = useState<number | null>(null);
  const [switchPenalty, setSwitchPenalty] = useState(0.8);
  const [vocabularyCorrectionEnabled, setVocabularyCorrectionEnabled] = useState(true);
  const [voiceProfiles, setVoiceProfiles] = useState<SpeakerProfile[]>([]);
  const [learnedVocab, setLearnedVocab] = useState<VocabularyEntry[]>([]);
  const [vocabProfiles, setVocabProfiles] = useState<VocabularyProfile[]>([]);
  const [newProfileName, setNewProfileName] = useState("");
  const [newProfileTerms, setNewProfileTerms] = useState("");
  const [savingVocabProfile, setSavingVocabProfile] = useState(false);

  useEffect(() => {
    loadPreferences();
  }, []);

  async function loadPreferences() {
    const p = await getPreferences();
    setDefaultVocab(p.default_vocabulary || "");
    setVoiceProfilesEnabled(p.speaker_profiles_enabled);
    setHfToken(p.hf_auth_token || "");
    setClusterThreshold(p.diarization?.clustering_threshold ?? null);
    setSwitchPenalty(p.speaker_switch_penalty ?? 0.8);
    setVocabularyCorrectionEnabled(p.vocabulary_correction?.enabled ?? true);
    setVoiceProfiles(await listSpeakerProfiles());
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

  async function handleDeleteVoiceProfile(id: string) {
    const voiceProfile = voiceProfiles.find((p) => p.id === id);
    if (!confirm(`Delete voice profile "${voiceProfile?.name}"?`)) return;
    await deleteSpeakerProfile(id);
    setVoiceProfiles(voiceProfiles.filter((p) => p.id !== id));
  }

  async function save() {
    await updatePreferences({
      default_vocabulary: defaultVocab,
      speaker_profiles_enabled: voiceProfilesEnabled,
      hf_auth_token: hfToken,
      speaker_switch_penalty: switchPenalty,
      vocabulary_correction: { enabled: vocabularyCorrectionEnabled },
      diarization: clusterThreshold == null ? {} : { clustering_threshold: clusterThreshold },
    });
  }

  return {
    defaultVocab, setDefaultVocab,
    voiceProfilesEnabled, setVoiceProfilesEnabled,
    hfToken, setHfToken,
    clusterThreshold, setClusterThreshold,
    switchPenalty, setSwitchPenalty,
    vocabularyCorrectionEnabled, setVocabularyCorrectionEnabled,
    voiceProfiles,
    learnedVocab, setLearnedVocab,
    vocabProfiles,
    newProfileName, setNewProfileName,
    newProfileTerms, setNewProfileTerms,
    savingVocabProfile,
    handleCreateVocabProfile,
    handleDeleteVocabProfile,
    handleDeleteVoiceProfile,
    save,
  };
}

export type PreferencesForm = ReturnType<typeof usePreferencesForm>;
