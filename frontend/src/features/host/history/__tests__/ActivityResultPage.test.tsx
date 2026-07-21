import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActivityResultPage } from "../ActivityResultPage";

const apiMocks = vi.hoisted(() => ({ getPublishedActivity: vi.fn() }));

vi.mock("../../../../api", () => ({ api: apiMocks }));
vi.mock("../../../../hooks/useDocumentTitle", () => ({ useDocumentTitle: vi.fn() }));

describe("ActivityResultPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("loads a published result without a host grant", async () => {
    apiMocks.getPublishedActivity.mockResolvedValue({
      roomId: "room-1",
      title: "Ethics seminar",
      createdAt: "2026-07-19T10:00:00.000Z",
      participantCount: 2,
      result: {
        generationMode: "placeholder",
        policy: "teach",
        trigger: "host",
        generatedAt: "2026-07-19T10:20:00.000Z",
        groups: [
          {
            id: "group-1",
            members: [
              { participantId: "participant-1", displayName: "Maya" },
              { participantId: "participant-2", displayName: "Alex" },
            ],
          },
        ],
      },
    });

    render(
      <MemoryRouter initialEntries={["/activities/room-1"]}>
        <Routes>
          <Route path="/activities/:roomId" element={<ActivityResultPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Ethics seminar")).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("Group 1: Maya, Alex.");
    expect(apiMocks.getPublishedActivity).toHaveBeenCalledWith("room-1", expect.any(AbortSignal));
  });
});
