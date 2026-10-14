import { describe, expect, it } from "vitest";
import { pointRequest, formatSize } from "./sources";

describe("pointRequest", () => {
  it("sends a system track as system_source and any other as source", () => {
    expect(pointRequest("system", " D:/p/s.wav ", true)).toEqual({ system_source: "D:/p/s.wav", adopt: false });
    expect(pointRequest("mic", "D:/p/m.wav", true)).toEqual({ source: "D:/p/m.wav", adopt: false });
    expect(pointRequest("audio", "D:/p/a.wav", true)).toEqual({ source: "D:/p/a.wav", adopt: false });
  });

  it("adopts only when the Meeting has no reference yet", () => {
    expect(pointRequest("audio", "D:/p/a.wav", false)).toEqual({ source: "D:/p/a.wav", adopt: true });
  });
});

describe("formatSize", () => {
  it("shows megabytes and gigabytes", () => {
    expect(formatSize(1_503_238_144)).toBe("1.4 GB");
    expect(formatSize(5_000_000)).toBe("4.8 MB");
  });
});
