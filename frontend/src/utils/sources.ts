import type { SourcesRequest } from "../types";

/** The request that points `track` at `path`. A Meeting with no reference yet is adopted. */
export function pointRequest(track: string, path: string, hasReference: boolean): SourcesRequest {
  const value = path.trim();
  const target = track === "system" ? { system_source: value } : { source: value };
  return { ...target, adopt: !hasReference };
}

export function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`;
}
