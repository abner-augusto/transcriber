import { describe, it, expect } from "vitest";
import { cleanParticipants, formatVocabulary, parseVocabulary } from "./vocabulary";

describe("cleanParticipants", () => {
  it("returns empty array for empty input", () => {
    expect(cleanParticipants("")).toEqual([]);
    expect(cleanParticipants("   ")).toEqual([]);
    expect(cleanParticipants(null as any)).toEqual([]);
  });

  it("splits on newlines", () => {
    expect(cleanParticipants("Alice\nBob\nCarol")).toEqual(["Alice", "Bob", "Carol"]);
  });

  it("splits on commas", () => {
    expect(cleanParticipants("Alice, Bob, Carol")).toEqual(["Alice", "Bob", "Carol"]);
  });

  it("splits on semicolons", () => {
    expect(cleanParticipants("Alice; Bob; Carol")).toEqual(["Alice", "Bob", "Carol"]);
  });

  it("splits on 'and'", () => {
    expect(cleanParticipants("Alice and Bob and Carol")).toEqual(["Alice", "Bob", "Carol"]);
  });

  it("strips parenthetical annotations", () => {
    expect(cleanParticipants("Alice Silva (Organizer)")).toEqual(["Alice Silva"]);
    expect(cleanParticipants("Bob (Host)")).toEqual(["Bob"]);
  });

  it("strips email addresses", () => {
    expect(cleanParticipants("alice@example.com")).toEqual(["alice"]);
    expect(cleanParticipants("Alice Silva <alice@example.com>")).toEqual(["Alice Silva"]);
  });

  it("strips trailing role/status markers", () => {
    expect(cleanParticipants("Bob: joined at 10:30")).toEqual(["Bob"]);
    expect(cleanParticipants("Carol - Host")).toEqual(["Carol"]);
  });

  it("strips trailing timestamps", () => {
    expect(cleanParticipants("Alice 10:30")).toEqual(["Alice"]);
    expect(cleanParticipants("Bob 14:25:30")).toEqual(["Bob"]);
  });

  it("deduplicates case-insensitively", () => {
    expect(cleanParticipants("Alice, alice, ALICE")).toEqual(["Alice"]);
  });

  it("preserves order of first occurrence", () => {
    expect(cleanParticipants("Bob, Alice, Bob")).toEqual(["Bob", "Alice"]);
  });

  it("handles mixed separators", () => {
    expect(cleanParticipants("Alice, Bob\nCarol; Dave and Eve")).toEqual(["Alice", "Bob", "Carol", "Dave", "Eve"]);
  });

  it("strips leading/trailing punctuation and handles list numbers", () => {
    expect(cleanParticipants("  Alice. ,  Bob,  ")).toEqual(["Alice", "Bob"]);
    expect(cleanParticipants("1. Alice\n2. Bob")).toEqual(["Alice", "Bob"]);
  });
});

describe("formatVocabulary", () => {
  it("returns null when both are empty", () => {
    expect(formatVocabulary([], "")).toBeNull();
  });

  it("formats speakers only", () => {
    expect(formatVocabulary(["Alice", "Bob"], "")).toBe("Speakers: Alice, Bob");
  });

  it("formats vocabulary only", () => {
    expect(formatVocabulary([], "Docker, Kubernetes")).toBe("Vocabulary: Docker, Kubernetes");
  });

  it("formats both speakers and vocabulary", () => {
    expect(formatVocabulary(["Alice", "Bob"], "Docker, Kubernetes")).toBe(
      "Speakers: Alice, Bob\nVocabulary: Docker, Kubernetes"
    );
  });

  it("preserves already-formatted vocabulary", () => {
    expect(formatVocabulary([], "Terms: Docker, Kubernetes")).toBe("Terms: Docker, Kubernetes");
  });
});

describe("parseVocabulary", () => {
  it("returns empty for null input", () => {
    expect(parseVocabulary(null)).toEqual({ speakers: [], vocabulary: "" });
  });

  it("parses structured format", () => {
    const result = parseVocabulary("Speakers: Alice, Bob\nVocabulary: Docker, Kubernetes");
    expect(result.speakers).toEqual(["Alice", "Bob"]);
    expect(result.vocabulary).toBe("Docker, Kubernetes");
  });

  it("parses unstructured text as vocabulary", () => {
    const result = parseVocabulary("Docker, Kubernetes, gRPC");
    expect(result.speakers).toEqual([]);
    expect(result.vocabulary).toBe("Docker, Kubernetes, gRPC");
  });

  it("parses Portuguese speaker label", () => {
    const result = parseVocabulary("Participantes: Alice, Bob");
    expect(result.speakers).toEqual(["Alice", "Bob"]);
  });
});
