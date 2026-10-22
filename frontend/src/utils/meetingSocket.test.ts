import { describe, expect, it } from "vitest";
import { MEETING_NOT_FOUND_CLOSE, meetingSocketAction, shouldReconnectMeetingSocket } from "./meetingSocket";

describe("meetingSocketAction", () => {
  it("ignores a ping", () => {
    expect(meetingSocketAction({ type: "ping" })).toEqual({ showProgress: false, refetch: false });
  });

  it("refetches, without touching the progress bar, when the Meeting changed elsewhere", () => {
    expect(meetingSocketAction({ type: "meeting_changed" })).toEqual({ showProgress: false, refetch: true });
  });

  it("refetches, without showing progress, when the Job was cancelled", () => {
    expect(meetingSocketAction({ type: "cancelled" })).toEqual({ showProgress: false, refetch: true });
  });

  it("shows and refetches a failure", () => {
    expect(meetingSocketAction({ type: "error", error: "boom" })).toEqual({ showProgress: true, refetch: true });
  });

  it("shows and refetches a finished Job", () => {
    expect(meetingSocketAction({ type: "progress", progress: 100 })).toEqual({ showProgress: true, refetch: true });
  });

  it("only shows a Job still running", () => {
    expect(meetingSocketAction({ type: "progress", progress: 48 })).toEqual({ showProgress: true, refetch: false });
  });
});

describe("shouldReconnectMeetingSocket", () => {
  it("never reconnects once the page has let go of the Meeting", () => {
    expect(shouldReconnectMeetingSocket({ closeCode: 1000, cancelled: true, visibilityState: "visible" })).toBe(false);
  });

  it("does not reconnect to a Meeting the server says is gone", () => {
    expect(
      shouldReconnectMeetingSocket({ closeCode: MEETING_NOT_FOUND_CLOSE, cancelled: false, visibilityState: "visible" }),
    ).toBe(false);
  });

  it("does not reconnect while the tab is hidden", () => {
    expect(shouldReconnectMeetingSocket({ closeCode: 1006, cancelled: false, visibilityState: "hidden" })).toBe(false);
  });

  it("reconnects a dropped socket for the Meeting on screen", () => {
    expect(shouldReconnectMeetingSocket({ closeCode: 1006, cancelled: false, visibilityState: "visible" })).toBe(true);
  });
});
