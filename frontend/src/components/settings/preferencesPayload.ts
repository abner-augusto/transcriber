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

export function buildSourceSearchPayload(roots: string[], depth: string) {
  if (!/^\d+$/.test(depth) || !Number.isSafeInteger(Number(depth))) {
    throw new Error("Search depth must be a whole number of 0 or more.");
  }
  if (roots.some((root) => !/^(?:\/|[a-zA-Z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)/.test(root))) {
    throw new Error("Enter an absolute path for each folder.");
  }
  return { source_roots: roots, source_search_depth: Number(depth) };
}
