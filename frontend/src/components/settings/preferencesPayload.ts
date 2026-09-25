import type { DiarizationPrefs } from "../../api";

export function buildDiarizationPayload(
  engine: NonNullable<DiarizationPrefs["engine"]>,
  clusteringThreshold: number | null,
): DiarizationPrefs {
  return {
    engine,
    ...(clusteringThreshold == null ? {} : { clustering_threshold: clusteringThreshold }),
  };
}
