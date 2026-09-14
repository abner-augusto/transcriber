import { describe, expect, it } from "vitest";
import type { Preset } from "../types";
import { firstUsablePreset } from "./engineHealth";

function preset(id: string, state: Preset["state"]): Preset {
  return {
    id, state, name: id, engine: "fixture", model_path: "fixture", available: state !== "blocked",
    reason: null, summary: state, fingerprint: id, checks: [],
  };
}

describe("firstUsablePreset", () => {
  it("never auto-selects a blocked Preset", () => {
    expect(firstUsablePreset([preset("blocked", "blocked"), preset("degraded", "degraded")])?.id).toBe("degraded");
  });

  it("prefers a different usable Preset for duplication", () => {
    expect(firstUsablePreset([preset("current", "ready"), preset("other", "ready")], "current")?.id).toBe("other");
  });

  it("returns no selection when every Preset is blocked", () => {
    expect(firstUsablePreset([preset("blocked", "blocked")])).toBeUndefined();
  });
});
