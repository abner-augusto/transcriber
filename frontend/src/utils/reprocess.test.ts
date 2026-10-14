import { describe, expect, it } from "vitest";
import { reprocessBlockedReason } from "./reprocess";

describe("reprocessBlockedReason", () => {
  it("is empty while the app can rerun the Meeting", () => {
    expect(reprocessBlockedReason({ reprocessable: true, sources: [] })).toBe("");
  });

  it("does not block a Meeting from an older server that sends no flag", () => {
    expect(reprocessBlockedReason({})).toBe("");
  });

  it("asks for an original when the Meeting has no reference to one", () => {
    expect(reprocessBlockedReason({ reprocessable: false, sources: [] })).toMatch(/no reference to the original/i);
  });

  it("lets the action run, and search, while a reference exists but its file is not where it was", () => {
    const stale = [{ track: "mic", name: "mic.wav", size: 5, path: "D:/x/mic.wav", state: "missing" as const }];
    expect(reprocessBlockedReason({ reprocessable: false, sources: stale })).toBe("");
  });
});
