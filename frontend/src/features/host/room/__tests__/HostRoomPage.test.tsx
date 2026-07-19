import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HostRoom } from "../../../../domain";
import { HostRoomPage } from "../HostRoomPage";

const apiMocks = vi.hoisted(() => ({
  getRoom: vi.fn(),
  getGroups: vi.fn(),
}));

vi.mock("../../../../api", () => {
  class ApiError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }

  return { api: apiMocks, ApiError };
});

vi.mock("../../../../hooks/useCountdown", () => ({
  useCountdown: () => 300,
}));

vi.mock("../../../../hooks/useDocumentTitle", () => ({
  useDocumentTitle: vi.fn(),
}));

vi.mock("../../../../hooks/usePolling", () => ({
  usePolling: vi.fn(),
}));

const room: HostRoom = {
  id: "room-1",
  joinCode: "J7KM4P",
  title: "Dynamic programming review",
  policy: "teach",
  groupSize: { minimum: 3, preferred: 4, maximum: 5 },
  status: "answering",
  durationMinutes: 20,
  serverTime: "2026-07-19T10:00:00.000Z",
  startedAt: "2026-07-19T09:55:00.000Z",
  deadlineAt: "2026-07-19T10:05:00.000Z",
  remainingSeconds: 300,
  activityStarted: true,
  questions: [
    {
      id: "question-1",
      position: 0,
      prompt: "Explain the state used in your solution.",
      referenceMaterial: null,
      coverageUnits: [{ id: "unit-1", text: "Defines the dynamic-programming state" }],
    },
  ],
  materials: [],
  progress: {
    participantCount: 4,
    submittedParticipantCount: 0,
    answeredResponseCount: 0,
    submittedResponseCount: 0,
    possibleResponseCount: 4,
  },
  allowedActions: ["viewProgress", "startAnalysis"],
  lastError: null,
  participants: [
    { participantId: "participant-1", displayName: "Maya Chen", submittedAt: null },
    { participantId: "participant-2", displayName: "Alex Kim", submittedAt: null },
    { participantId: "participant-3", displayName: "Sam Lee", submittedAt: null },
    { participantId: "participant-4", displayName: "Noor Ali", submittedAt: null },
  ],
  analysisPhase: "not_started",
};

describe("HostRoomPage", () => {
  beforeEach(() => {
    apiMocks.getRoom.mockResolvedValue(room);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("does not place the per-second countdown inside a live status region", async () => {
    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const countdown = await screen.findByText("5:00 remaining");
    const liveAncestor = countdown.closest(
      '[aria-live="polite"], [aria-live="assertive"], [role="status"]:not([aria-live="off"])',
    );

    expect(liveAncestor).toBeNull();
  });
});
