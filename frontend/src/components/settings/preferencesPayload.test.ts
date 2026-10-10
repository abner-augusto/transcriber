import { describe, expect, it } from "vitest";
import { buildDiarizationPayload } from "./preferencesPayload";

const nemotron = { speechThreshold: 0.5, minSpeakerSeconds: 5 };

describe("buildDiarizationPayload", () => {
  it("saves pyannote with its default threshold", () => {
    expect(buildDiarizationPayload({ engine: "pyannote", clusteringThreshold: null, ...nemotron })).toEqual({
      engine: "pyannote",
      speech_threshold: 0.5,
      min_speaker_seconds: 5,
    });
  });

  it("saves a pyannote threshold override", () => {
    expect(buildDiarizationPayload({ engine: "pyannote", clusteringThreshold: 0.63, ...nemotron })).toEqual({
      engine: "pyannote",
      clustering_threshold: 0.63,
      speech_threshold: 0.5,
      min_speaker_seconds: 5,
    });
  });

  it("keeps the stored threshold while Nemotron is selected", () => {
    expect(
      buildDiarizationPayload({ engine: "nemotron-3-diarization", clusteringThreshold: 0.63, ...nemotron }),
    ).toEqual({
      engine: "nemotron-3-diarization",
      clustering_threshold: 0.63,
      speech_threshold: 0.5,
      min_speaker_seconds: 5,
    });
  });

  it("saves Nemotron's own values", () => {
    expect(
      buildDiarizationPayload({
        engine: "nemotron-3-diarization",
        clusteringThreshold: null,
        speechThreshold: 0.35,
        minSpeakerSeconds: 3,
      }),
    ).toEqual({ engine: "nemotron-3-diarization", speech_threshold: 0.35, min_speaker_seconds: 3 });
  });

  it("still sends the Nemotron values after switching to pyannote, because the PUT replaces the block", () => {
    expect(
      buildDiarizationPayload({
        engine: "pyannote",
        clusteringThreshold: null,
        speechThreshold: 0.35,
        minSpeakerSeconds: 3,
      }),
    ).toEqual({ engine: "pyannote", speech_threshold: 0.35, min_speaker_seconds: 3 });
  });
});
