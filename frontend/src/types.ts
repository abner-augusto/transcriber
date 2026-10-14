export interface SourceInfo {
  track: "audio" | "mic" | "system" | string;
  name: string;
  size: number;
  path: string | null;
  state: "present" | "missing" | "not saved";
}

export interface SourcesRequest {
  source?: string;
  system_source?: string;
  adopt: boolean;
}

export interface Meeting {
  id: string;
  title: string;
  status: "uploaded" | "processing" | "completed" | "failed";
  original_filename: string | null;
  is_dual_track?: boolean | null;
  /** False for a dual-track Meeting whose original recordings the app cannot read now. */
  reprocessable?: boolean;
  /** The Source References: where each original recording lives outside the app. */
  sources?: SourceInfo[];
  duration: number | null;
  preset_id: string | null;
  min_speakers: number | null;
  max_speakers: number | null;
  vocabulary: string | null;
  participants: string | null;
  created_at: string;
  updated_at: string;
  speaker_count: number;
  segment_count: number;
  speakers?: Speaker[];
  segments?: Segment[];
  review_notes?: ReviewNote[];
}

export type ReviewNoteKind =
  | "comment"
  | "question"
  | "text"
  | "speaker_name"
  | "speaker_move"
  | "speaker_merge"
  | "split";

export type ReviewNoteStatus = "open" | "answered" | "accepted" | "dismissed" | "done";

export interface ReviewNote {
  id: string;
  meeting_id: string;
  start_time: number;
  end_time: number;
  author: "agent" | "user" | "system";
  kind: ReviewNoteKind;
  body: string;
  payload: Record<string, string | number> | null;
  status: ReviewNoteStatus;
  answer: string | null;
  reply: string | null;
  created_at: string | null;
  resolved_at: string | null;
}

export interface Speaker {
  id: string;
  meeting_id: string;
  label: string;
  display_name: string | null;
  color: string;
  identified_by: string | null;
  confidence: number | null;
  total_speaking_time: number;
  segment_count: number;
}

/** A Vocabulary Correction in a Segment; offsets are absent on data from before plan 041. */
export interface Correction {
  start: number;
  end: number;
  heard: string;
  term: string;
  rule: string;
  text_start?: number;
  text_end?: number;
  confirmed?: boolean;
}

export interface Segment {
  id: string;
  meeting_id: string;
  speaker_id: string | null;
  speaker_label: string | null;
  speaker_name: string | null;
  speaker_color: string | null;
  start_time: number;
  end_time: number;
  text: string;
  original_text: string | null;
  order: number;
  is_edited: boolean;
  confidence: number | null;
  corrections?: Correction[];
}

export interface Job {
  id: string;
  meeting_id: string;
  job_type: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  current_step: string | null;
  error: string | null;
  run_config: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface ProgressUpdate {
  type: "progress" | "error" | "ping" | "meeting_changed";
  progress?: number;
  step?: string;
  status?: string;
  error?: string;
  message?: string;
}

export interface Preset {
  id: string;
  name: string;
  engine: string;
  model_path: string;
  aligner_path?: string | null;
  language?: string | null;
  decoder?: string | null;
  device?: string | null;
  compute_type?: string | null;
  vad_filter?: boolean | null;
  available: boolean;
  reason: string | null;
  state: "ready" | "degraded" | "blocked";
  summary: string;
  fingerprint: string;
  checks: EngineCheck[];
}

export interface EngineCheck {
  code: string;
  required: boolean;
  passed: boolean;
  message: string;
}

export interface ModelSettings {
  presets: Preset[];
  default_preset: string;
  engines: string[];
}

export interface VocabularyProfile {
  id: string;
  name: string;
  terms: string;
}
