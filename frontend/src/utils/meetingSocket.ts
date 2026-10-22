import type { ProgressUpdate } from "../types";

/** The server closes a Meeting's progress socket with this code when the Meeting is gone. */
export const MEETING_NOT_FOUND_CLOSE = 4004;
export const RECONNECT_DELAY_MS = 3000;

/**
 * Whether a closed Meeting progress socket should be reopened.
 *
 * Never after the page has let go of the Meeting (`cancelled`), never for a Meeting
 * the server says does not exist, and only while the tab is visible.
 */
export function shouldReconnectMeetingSocket(opts: {
  closeCode: number;
  cancelled: boolean;
  visibilityState: string;
}): boolean {
  if (opts.cancelled) return false;
  if (opts.closeCode === MEETING_NOT_FOUND_CLOSE) return false;
  return opts.visibilityState === "visible";
}

/** What the Meeting page does with one socket event. */
export function meetingSocketAction(event: ProgressUpdate): { showProgress: boolean; refetch: boolean } {
  if (event.type === "ping") return { showProgress: false, refetch: false };
  // The Job was cancelled and the Meeting is back where it was: read it again, show no progress.
  if (event.type === "meeting_changed" || event.type === "cancelled") return { showProgress: false, refetch: true };
  const finished = event.type === "error" || (event.type === "progress" && event.progress === 100);
  return { showProgress: true, refetch: finished };
}
