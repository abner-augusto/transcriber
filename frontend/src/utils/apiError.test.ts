import { describe, it, expect } from "vitest";
import { AxiosError } from "axios";
import type { AxiosResponse } from "axios";
import { apiErrorMessage } from "./apiError";

function refusal(data: unknown): AxiosError {
  return new AxiosError("Request failed", "ERR_BAD_REQUEST", undefined, undefined, {
    status: 409,
    data,
  } as AxiosResponse);
}

describe("apiErrorMessage", () => {
  it("shows the API's detail message", () => {
    expect(apiErrorMessage(refusal({ detail: "No Correction starts there" }))).toBe(
      "No Correction starts there",
    );
  });

  it("falls back when the detail is not a string", () => {
    expect(apiErrorMessage(refusal({ detail: [{ msg: "bad" }] }))).toBe("Something went wrong. Try again.");
  });

  it("falls back for errors that are not API refusals", () => {
    expect(apiErrorMessage(new Error("network down"))).toBe("Something went wrong. Try again.");
  });
});
