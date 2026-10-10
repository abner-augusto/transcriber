import { describe, it, expect } from "vitest";
import type { Correction } from "../types";
import { correctionPieces } from "./corrections";

function correction(heard: string, term: string, text_start?: number, text_end?: number): Correction {
  return { start: 0, end: 1, heard, term, rule: "misheard", text_start, text_end };
}

describe("correctionPieces", () => {
  it("returns the whole text as one piece when there are no Corrections", () => {
    expect(correctionPieces("falou com o Galo ontem", [])).toEqual([{ text: "falou com o Galo ontem" }]);
  });

  it("marks two Corrections in the middle", () => {
    const a = correction("Galo", "Garrah", 12, 18);
    const b = correction("ontem", "Onthem", 19, 25);
    expect(correctionPieces("falou com o Garrah Onthem fim", [a, b])).toEqual([
      { text: "falou com o " },
      { text: "Garrah", correction: a },
      { text: " " },
      { text: "Onthem", correction: b },
      { text: " fim" },
    ]);
  });

  it("marks Corrections at offset 0 and at the end without empty pieces", () => {
    const a = correction("galo", "Garrah", 0, 6);
    const b = correction("fim", "Fym", 11, 14);
    expect(correctionPieces("Garrah foi Fym", [a, b])).toEqual([
      { text: "Garrah", correction: a },
      { text: " foi " },
      { text: "Fym", correction: b },
    ]);
  });

  it("ignores a Correction without offsets", () => {
    const old = correction("Galo", "Garrah");
    expect(correctionPieces("falou com o Garrah", [old])).toEqual([{ text: "falou com o Garrah" }]);
  });

  it("orders Corrections by offset", () => {
    const a = correction("x", "bb", 3, 5);
    const b = correction("y", "aa", 0, 2);
    expect(correctionPieces("aa bb", [a, b])).toEqual([
      { text: "aa", correction: b },
      { text: " " },
      { text: "bb", correction: a },
    ]);
  });

  it("ignores out-of-range and empty offsets and covers the text exactly once", () => {
    const text = "um dois tres";
    const outside = correction("a", "b", 8, 40);
    const negative = correction("a", "b", -2, 3);
    const empty = correction("a", "b", 4, 4);
    const inverted = correction("a", "b", 7, 5);
    const pieces = correctionPieces(text, [outside, negative, empty, inverted]);
    expect(pieces).toEqual([{ text }]);
  });

  it("keeps the first of two overlapping Corrections and covers the text once", () => {
    const first = correction("a", "um do", 0, 5);
    const second = correction("b", "do is", 3, 8);
    const pieces = correctionPieces("um dois tres", [first, second]);
    expect(pieces).toEqual([
      { text: "um do", correction: first },
      { text: "is tres" },
    ]);
    expect(pieces.map((p) => p.text).join("")).toBe("um dois tres");
  });
});
