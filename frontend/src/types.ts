export interface Meeting {
  id: string;
  title: string;
  status: "uploaded" | "processing" | "completed" | "failed";
  original_filename: string | null;
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
}

export interface Job {
  id: string;
  meeting_id: string;
  job_type: string;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  current_step: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface ProgressUpdate {
  type: "progress" | "error" | "ping";
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
