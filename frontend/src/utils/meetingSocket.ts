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
