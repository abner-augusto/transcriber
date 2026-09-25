import { describe, expect, it } from "vitest";
import type { Preset } from "../types";
import { engineHealthDot, firstUsablePreset } from "./engineHealth";

describe("engineHealthDot", () => {
  it("colors each health state distinctly", () => {
    expect(engineHealthDot("ready")).toContain("emerald");
    expect(engineHealthDot("degraded")).toContain("amber");
    expect(engineHealthDot("blocked")).toContain("red");
  });
});

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
