import { describe, expect, it } from "vitest";
import { reprocessBlockedReason } from "./reprocess";

describe("reprocessBlockedReason", () => {
  it("is empty while the app can rerun the Meeting from the audio it holds", () => {
    expect(reprocessBlockedReason({ reprocessable: true })).toBe("");
  });

  it("explains that a dual-track Meeting lost its tracks", () => {
    expect(reprocessBlockedReason({ reprocessable: false })).toMatch(/mic and system tracks/);
  });

  it("does not block a Meeting from an older server that sends no flag", () => {
    expect(reprocessBlockedReason({})).toBe("");
  });
});
