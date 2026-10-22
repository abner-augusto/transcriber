import type { FoundTrack, Meeting, TrackSelector, TracksRequest } from "../types";

/** `1` for a stream, `0:1` for a channel of it: what a select option carries and the CLI accepts. */
export function trackKey(track: TrackSelector): string {
  return track.channel === null ? String(track.stream) : `${track.stream}:${track.channel}`;
}

export function parseTrackKey(key: string): TrackSelector {
  const [stream, channel] = key.split(":");
  return { stream: Number(stream), channel: channel === undefined ? null : Number(channel) };
}

/** What was found, in the words of a recorder: tracks count from 1. */
export function describeTrack(track: FoundTrack): string {
  const name =
    track.channel !== null
      ? track.channel === 0
        ? "Left channel"
        : track.channel === 1
          ? "Right channel"
          : `Channel ${track.channel + 1}`
      : track.title
        ? `Track ${track.stream + 1} "${track.title}"`
        : `Track ${track.stream + 1}`;
  return `${name} · ${track.status} · ${track.level_db.toFixed(1)} dB`;
}

/** The request for the chosen mic and system, or null when the choice cannot be sent. */
export function tracksRequest(micKey: string, systemKey: string): TracksRequest | null {
  if (!micKey || micKey === systemKey) return null;
  return {
    mic: parseTrackKey(micKey),
    system: systemKey ? parseTrackKey(systemKey) : null,
  };
}

/** Tracks can be chosen before processing, for a file that had several to tell apart. */
export function canChooseTracks(meeting: Pick<Meeting, "status" | "track_layout">): boolean {
  return meeting.status === "uploaded" && !!meeting.track_layout;
}
