import type { Meeting } from "../types";

/** Why Full reprocess, Re-diarize and Duplicate are unavailable, or "" when they are. */
export function reprocessBlockedReason(meeting: Pick<Meeting, "reprocessable">): string {
  if (meeting.reprocessable !== false) return "";
  return "Needs the mic and system tracks, which are not kept after processing";
}
