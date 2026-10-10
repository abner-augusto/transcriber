import axios from "axios";

/** The API's `detail` message for a refused request, else a generic one. */
export function apiErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return "Something went wrong. Try again.";
}
