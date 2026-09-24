import { describe, expect, it } from "vitest";
import { DEFAULT_ENGINE_META, engineMeta } from "./engineMetadata";

describe("engineMeta", () => {
  it("describes a known Engine", () => {
    expect(engineMeta("vibevoice").supportsAligner).toBe(true);
    expect(engineMeta("parakeet.cpp").supportsDecoder).toBe(true);
  });

  it("falls back to the generic entry for an unknown Engine", () => {
    expect(engineMeta("unknown-engine")).toBe(DEFAULT_ENGINE_META);
    expect(engineMeta("unknown-engine").modelPlaceholder).toBe("Model path or identifier");
  });
});
