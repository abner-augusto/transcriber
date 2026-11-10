// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import HomePage from "./HomePage";

vi.mock("../api", () => ({
  listMeetings: vi.fn().mockResolvedValue([{ id: "meeting-1", title: "Interview", status: "completed", created_at: "2026-01-01", duration: 60, speaker_count: 0, segment_count: 1 }]),
  searchSegments: vi.fn().mockResolvedValue([{ meeting_id: "meeting-1", meeting_title: "Interview", segments: [{ id: "segment-1", start_time: 12, text: "matching words" }] }]),
  updateMeetingTitle: vi.fn().mockResolvedValue({ title: "Renamed" }),
  deleteMeeting: vi.fn().mockResolvedValue(undefined),
}));

afterEach(cleanup);

it("offers meeting links on cards and search results while keeping card controls usable", async () => {
  const user = userEvent.setup();
  render(<MemoryRouter><Routes><Route path="/" element={<HomePage />} /><Route path="/meetings/:id" element={<div>Meeting page</div>} /></Routes></MemoryRouter>);

  const cardLink = await screen.findByRole("link", { name: "Interview" });
  expect(cardLink.getAttribute("href")).toBe("/meetings/meeting-1");
  await user.click(screen.getByTitle("Rename"));
  const rename = screen.getByDisplayValue("Interview");
  await user.clear(rename);
  await user.type(rename, "Renamed{Enter}");
  await screen.findByText("Renamed");
  expect(screen.queryByText("Meeting page")).toBeNull();
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(screen.getByTitle("Delete"));
  expect(screen.queryByText("Meeting page")).toBeNull();

  await user.type(screen.getByPlaceholderText("Search across all transcriptions..."), "matching");
  const segment = await screen.findByRole("link", { name: /matching words/ });
  expect(segment.getAttribute("href")).toBe("/meetings/meeting-1");
  expect(screen.getByRole("link", { name: "Interview" }).getAttribute("href")).toBe("/meetings/meeting-1");
  await user.click(segment);
  await waitFor(() => expect(screen.getByText("Meeting page")).toBeTruthy());
});
