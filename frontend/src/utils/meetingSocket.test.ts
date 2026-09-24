import { describe, expect, it } from "vitest";
import { MEETING_NOT_FOUND_CLOSE, shouldReconnectMeetingSocket } from "./meetingSocket";

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
