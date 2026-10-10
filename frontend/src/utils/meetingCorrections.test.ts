import { describe, it, expect } from "vitest";
import type { Correction, Segment } from "../types";
import { meetingCorrections } from "./meetingCorrections";

function correction(start: number, confirmed?: boolean, withOffsets = true): Correction {
  return {
    start,
    end: start + 1,
    heard: `heard${start}`,
    term: `Term${start}`,
    rule: "misheard",
    text_start: withOffsets ? 0 : undefined,
    text_end: withOffsets ? 5 : undefined,
    confirmed,
  };
}

function segment(id: string, order: number, corrections?: Correction[]): Segment {
  return { id, order, corrections } as Segment;
}

describe("meetingCorrections", () => {
  it("gives two empty lists when there are no Segments", () => {
    expect(meetingCorrections([])).toEqual({ toReview: [], confirmed: [] });
  });

  it("splits confirmed from unconfirmed across Segments, each sorted by time", () => {
    const a = correction(30);
    const b = correction(10, true);
    const c = correction(5);
    const d = correction(50, true);
    const segments = [segment("s2", 2, [a, b]), segment("s1", 1, [d, c]), segment("s0", 0)];
    expect(meetingCorrections(segments)).toEqual({
      toReview: [
        { segmentId: "s1", order: 1, correction: c },
        { segmentId: "s2", order: 2, correction: a },
      ],
      confirmed: [
        { segmentId: "s2", order: 2, correction: b },
        { segmentId: "s1", order: 1, correction: d },
      ],
    });
  });

  it("skips Corrections without offsets", () => {
    const legacy = correction(1, false, false);
    const kept = correction(2);
    expect(meetingCorrections([segment("s1", 1, [legacy, kept])])).toEqual({
      toReview: [{ segmentId: "s1", order: 1, correction: kept }],
      confirmed: [],
    });
  });
});
