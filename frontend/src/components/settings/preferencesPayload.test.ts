import { describe, expect, it } from "vitest";
import { buildDiarizationPayload } from "./preferencesPayload";

describe("buildDiarizationPayload", () => {
  it("saves pyannote with its default threshold", () => {
    expect(buildDiarizationPayload("pyannote", null)).toEqual({ engine: "pyannote" });
  });

  it("saves a pyannote threshold override", () => {
    expect(buildDiarizationPayload("pyannote", 0.63)).toEqual({ engine: "pyannote", clustering_threshold: 0.63 });
  });

  it("keeps the stored threshold while Nemotron is selected", () => {
    expect(buildDiarizationPayload("nemotron-3-diarization", 0.63)).toEqual({
      engine: "nemotron-3-diarization",
      clustering_threshold: 0.63,
    });
  });
});
