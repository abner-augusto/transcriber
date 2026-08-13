import axios from "axios";
import type { Meeting, Segment, Speaker, Job, ModelSettings, Preset } from "./types";

const api = axios.create({ baseURL: "/api" });

export async function listMeetings(): Promise<Meeting[]> {
  const { data } = await api.get("/meetings");
  return data;
}

export async function createMeeting(form: FormData): Promise<Meeting> {
  const { data } = await api.post("/meetings", form);
  return data;
}

export async function getMeeting(id: string): Promise<Meeting> {
  const { data } = await api.get(`/meetings/${id}`);
  return data;
}

export async function deleteMeeting(id: string): Promise<void> {
  await api.delete(`/meetings/${id}`);
}

export async function updateMeetingTitle(id: string, title: string): Promise<Meeting> {
  const { data } = await api.put(`/meetings/${id}`, { title });
  return data;
}

export async function startProcessing(id: string, skipLlm = false): Promise<Job> {
  const { data } = await api.post(`/meetings/${id}/process`, { skip_llm: skipLlm });
  return data;
}

export async function rediarizeMeeting(id: string): Promise<Job> {
  const { data } = await api.post(`/meetings/${id}/rediarize`);
  return data;
}

export async function reidentifyMeeting(id: string): Promise<Job> {
  const { data } = await api.post(`/meetings/${id}/reidentify`);
  return data;
}

export async function getJobs(meetingId: string): Promise<Job[]> {
  const { data } = await api.get(`/meetings/${meetingId}/jobs`);
  return data;
}

export async function updateSegmentText(
  id: string,
  text: string
): Promise<Segment> {
  const { data } = await api.put(`/segments/${id}`, { text });
  return data;
}

export async function updateSegmentSpeaker(
  id: string,
  speakerId: string
): Promise<Segment> {
  const { data } = await api.put(`/segments/${id}/speaker`, {
    speaker_id: speakerId,
  });
  return data;
}

export async function updateSpeaker(
  id: string,
  updates: { display_name?: string; color?: string }
): Promise<Speaker> {
  const { data } = await api.put(`/speakers/${id}`, updates);
  return data;
}

export async function mergeSpeakers(
  sourceId: string,
  targetId: string
): Promise<Speaker> {
  const { data } = await api.post("/speakers/merge", {
    source_id: sourceId,
    target_id: targetId,
  });
  return data;
}

export function getAudioUrl(meetingId: string): string {
  return `/api/meetings/${meetingId}/audio`;
}

export function getExportUrl(meetingId: string, format: string): string {
  return `/api/meetings/${meetingId}/export?format=${format}`;
}

// --- Model Settings ---

export async function getModelSettings(): Promise<ModelSettings> {
  const { data } = await api.get("/model-settings");
  return data;
}

export async function setDefaultPreset(presetId: string): Promise<{ default_preset: string }> {
  const { data } = await api.put("/model-settings", { default_preset: presetId });
  return data;
}

export async function createModelPreset(preset: {
  name: string;
  engine: string;
  model_path: string;
  language?: string;
  decoder?: string;
}): Promise<Preset> {
  const { data } = await api.post("/model-settings/presets", preset);
  return data;
}

export async function deleteModelPreset(presetId: string) {
  await api.delete(`/model-settings/presets/${presetId}`);
}

// --- Search ---

export interface SearchResult {
  meeting_id: string;
  meeting_title: string;
  segments: {
    id: string;
    start_time: number;
    end_time: number;
    text: string;
    order: number;
    speaker_name: string | null;
    speaker_color: string | null;
  }[];
}

export async function searchSegments(q: string): Promise<SearchResult[]> {
  const { data } = await api.get("/search", { params: { q } });
  return data;
}

// --- Speaker Profiles ---

export interface SpeakerProfile {
  id: string;
  name: string;
  sample_count: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export async function listSpeakerProfiles(): Promise<SpeakerProfile[]> {
  const { data } = await api.get("/speaker-profiles");
  return data;
}

export async function deleteSpeakerProfile(id: string): Promise<void> {
  await api.delete(`/speaker-profiles/${id}`);
}

export async function saveProfileFromSpeaker(
  speakerId: string,
  meetingId: string,
  name?: string
): Promise<SpeakerProfile> {
  const { data } = await api.post("/speaker-profiles/save-from-speaker", {
    speaker_id: speakerId,
    meeting_id: meetingId,
    name: name || null,
  });
  return data;
}

// --- Preferences ---

export interface Preferences {
  default_vocabulary: string;
  speaker_profiles_enabled: boolean;
  hf_auth_token: string;
}

export async function getPreferences(): Promise<Preferences> {
  const { data } = await api.get("/settings");
  return data.preferences;
}

export async function updatePreferences(prefs: Partial<Preferences>): Promise<Preferences> {
  const { data } = await api.put("/settings/preferences", prefs);
  return data;
}

// --- Vocabulary Learning ---

export interface VocabularyEntry {
  id: string;
  term: string;
  frequency: number;
  source_meeting_id: string | null;
  created_at: string;
}

export async function listVocabulary(): Promise<VocabularyEntry[]> {
  const { data } = await api.get("/vocabulary");
  return data;
}

export async function deleteVocabularyEntry(id: string): Promise<void> {
  await api.delete(`/vocabulary/${id}`);
}

export async function suggestVocabulary(): Promise<{ terms: string[]; text: string }> {
  const { data } = await api.get("/vocabulary/suggest");
  return data;
}

// --- Speaker Analytics ---

export async function getSpeakerAnalytics(meetingId: string): Promise<{
  speakers: {
    name: string;
    color: string;
    speaking_time: number;
    segment_count: number;
    percentage: number;
    timeline: { start: number; end: number }[];
  }[];
  total_duration: number;
  total_speaking_time: number;
  silence_percentage: number;
}> {
  const { data } = await api.get(`/meetings/${meetingId}/analytics`);
  return data;
}
