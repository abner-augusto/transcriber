import { describe, expect, it } from "vitest";
import type { TrackLayout } from "../types";
import { canChooseTracks, describeTrack, parseTrackKey, trackKey, tracksRequest } from "./tracks";

const OBS: TrackLayout = {
  tracks: [
    { stream: 0, channel: null, title: null, status: "mix", level_db: -18 },
    { stream: 1, channel: null, title: "Mic", status: "speech", level_db: -24.04 },
    { stream: 2, channel: null, title: "Desktop", status: "speech", level_db: -27 },
  ],
  mic: { stream: 1, channel: null },
  system: { stream: 2, channel: null },
  audio: null,
  manual: false,
};

describe("trackKey", () => {
  it("names a whole stream by its number and a channel as stream:channel", () => {
    expect(trackKey({ stream: 1, channel: null })).toBe("1");
    expect(trackKey({ stream: 0, channel: 1 })).toBe("0:1");
  });

  it("is read back by parseTrackKey", () => {
    expect(parseTrackKey("1")).toEqual({ stream: 1, channel: null });
    expect(parseTrackKey("0:1")).toEqual({ stream: 0, channel: 1 });
  });
});

describe("describeTrack", () => {
  it("numbers tracks from 1 as a recorder does, and says what was found", () => {
    expect(describeTrack(OBS.tracks[1])).toBe('Track 2 "Mic" · speech · -24.0 dB');
  });

  it("calls the channels of a stereo stream left and right", () => {
    const left = { stream: 0, channel: 0, title: null, status: "speech" as const, level_db: -20 };
    const right = { ...left, channel: 1, status: "duplicate" as const };
    expect(describeTrack(left)).toBe("Left channel · speech · -20.0 dB");
    expect(describeTrack(right)).toBe("Right channel · duplicate · -20.0 dB");
  });

  it("names a track without a title by its number alone", () => {
    expect(describeTrack(OBS.tracks[0])).toBe("Track 1 · mix · -18.0 dB");
  });
});

describe("tracksRequest", () => {
  it("sends the chosen mic and system as selectors", () => {
    expect(tracksRequest("2", "1")).toEqual({
      mic: { stream: 2, channel: null },
      system: { stream: 1, channel: null },
    });
  });

  it("reads the file as one track when no system is chosen", () => {
    expect(tracksRequest("1", "")).toEqual({ mic: { stream: 1, channel: null }, system: null });
  });

  it("refuses the same track twice", () => {
    expect(tracksRequest("1", "1")).toBeNull();
  });

  it("refuses a missing mic", () => {
    expect(tracksRequest("", "1")).toBeNull();
  });
});

describe("canChooseTracks", () => {
  it("is open only before processing, for a file that has several tracks", () => {
    expect(canChooseTracks({ status: "uploaded", track_layout: OBS })).toBe(true);
    expect(canChooseTracks({ status: "completed", track_layout: OBS })).toBe(false);
    expect(canChooseTracks({ status: "uploaded", track_layout: null })).toBe(false);
    expect(canChooseTracks({ status: "uploaded" })).toBe(false);
  });
});
