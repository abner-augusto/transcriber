import type { Meeting } from "../types";

/** Why Full reprocess, Re-diarize and Duplicate are unavailable, or "" when they can be tried.
 *
 * A dual-track Meeting needs its original recordings. With a reference whose file moved
 * the actions still run: the server searches the configured folders and, failing that,
 * answers with how to re-point the source, which the page shows. */
export function reprocessBlockedReason(meeting: Pick<Meeting, "reprocessable" | "sources">): string {
  if (meeting.reprocessable !== false) return "";
  if ((meeting.sources ?? []).length > 0) return "";
  return "No reference to the original recording; attach it under Original recording";
}
