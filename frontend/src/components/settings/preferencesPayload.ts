import type { DiarizationPrefs } from "../../api";

// The PUT replaces the whole diarization block, so every Nemotron value is always sent.
export function buildDiarizationPayload({
  engine,
  clusteringThreshold,
  speechThreshold,
  minSpeakerSeconds,
}: {
  engine: NonNullable<DiarizationPrefs["engine"]>;
  clusteringThreshold: number | null;
  speechThreshold: number;
  minSpeakerSeconds: number;
}): DiarizationPrefs {
  return {
    engine,
    ...(clusteringThreshold == null ? {} : { clustering_threshold: clusteringThreshold }),
    speech_threshold: speechThreshold,
    min_speaker_seconds: minSpeakerSeconds,
  };
}
