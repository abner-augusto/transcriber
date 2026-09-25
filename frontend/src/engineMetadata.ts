/** How the Settings UI describes each transcription Engine: labels, badges, and form fields. */

export interface EngineMetadata {
  label: string;
  badgeText: string;
  badgeStyle: string;
  badgeDot: string;
  badgeTitle: string;
  description?: string;
  modelPlaceholder: string;
  alignerPlaceholder?: string;
  supportsAligner?: boolean;
  supportsLanguage?: boolean;
  supportsDecoder?: boolean;
  supportsDevice?: boolean;
  defaultLanguage?: string;
  defaultDevice?: string;
}

export const ENGINE_METADATA: Record<string, EngineMetadata> = {
  "vibevoice": {
    label: "VibeVoice 7B",
    badgeText: "Native Diarization (7B)",
    badgeStyle: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    badgeDot: "bg-emerald-400",
    badgeTitle: "Unified transcription and speaker diarization in a single pass",
    description: "Performs unified transcription and native speaker diarization with high accuracy, bypassing external diarization.",
    modelPlaceholder: "./models/VibeVoice-ASR-Streaming-7B or HuggingFace repo",
    alignerPlaceholder: "./models/Qwen3-ForcedAligner-0.6B-hf",
    supportsAligner: true,
    supportsDevice: true,
    defaultDevice: "cuda",
  },
  "qwen3-asr": {
    label: "Qwen3 1.7B",
    badgeText: "External Diarization",
    badgeStyle: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
    badgeDot: "bg-indigo-400",
    badgeTitle: "Qwen3 transcription with forced alignment, followed by external diarization",
    description: "Transcribes with Qwen3 1.7B with hotword vocabulary injection; diarization is handled externally.",
    modelPlaceholder: "./models/Qwen3-ASR-1.7B-hf or HuggingFace repo",
    alignerPlaceholder: "./models/Qwen3-ForcedAligner-0.6B-hf",
    supportsAligner: true,
    supportsLanguage: true,
    supportsDevice: true,
    defaultLanguage: "Portuguese",
    defaultDevice: "cuda",
  },
  "faster-whisper": {
    label: "Faster Whisper",
    badgeText: "External Diarization",
    badgeStyle: "bg-slate-800 text-slate-400 border-slate-700/50",
    badgeDot: "bg-slate-500",
    badgeTitle: "Transcription followed by external diarization",
    modelPlaceholder: "Model (e.g. large-v3-turbo, inesc-id/WhisperLv3-X-PT-All)",
    supportsLanguage: true,
    supportsDevice: true,
    defaultDevice: "auto",
  },
  "whisper.cpp": {
    label: "Whisper.cpp",
    badgeText: "External Diarization",
    badgeStyle: "bg-slate-800 text-slate-400 border-slate-700/50",
    badgeDot: "bg-slate-500",
    badgeTitle: "Transcription followed by external diarization",
    modelPlaceholder: "Model path (e.g. ./models/ggml-medium.bin)",
    supportsLanguage: true,
  },
  "parakeet.cpp": {
    label: "Parakeet.cpp",
    badgeText: "External Diarization",
    badgeStyle: "bg-slate-800 text-slate-400 border-slate-700/50",
    badgeDot: "bg-slate-500",
    badgeTitle: "Transcription followed by external diarization",
    modelPlaceholder: "Model path (e.g. ./models/parakeet/tdt-0.6b-v3-q8_0.gguf)",
    supportsDecoder: true,
  },
};

export const DEFAULT_ENGINE_META: EngineMetadata = {
  label: "Transcription Engine",
  badgeText: "External Diarization",
  badgeStyle: "bg-slate-800 text-slate-400 border-slate-700/50",
  badgeDot: "bg-slate-500",
  badgeTitle: "Transcription followed by external diarization",
  modelPlaceholder: "Model path or identifier",
};

/** The metadata for an Engine, falling back to a generic entry for Engines the UI does not know. */
export function engineMeta(engine: string): EngineMetadata {
  return ENGINE_METADATA[engine] || DEFAULT_ENGINE_META;
}
