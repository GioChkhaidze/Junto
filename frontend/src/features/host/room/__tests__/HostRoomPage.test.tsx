import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HostRoom } from "../../../../domain";
import { HostRoomPage } from "../HostRoomPage";

const apiMocks = vi.hoisted(() => ({
  getRoom: vi.fn(),
  getGroups: vi.fn(),
  getSyntheticClassroom: vi.fn(),
  configureSyntheticCohort: vi.fn(),
  generateSyntheticResponses: vi.fn(),
  retryAnalysis: vi.fn(),
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

vi.mock("../../../../hooks/useCountdown", () => ({ useCountdown: () => 300 }));

vi.mock("../../../../hooks/useDocumentTitle", () => ({ useDocumentTitle: vi.fn() }));

vi.mock("../../../../hooks/usePolling", () => ({ usePolling: vi.fn() }));

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
  startEligibility: {
    eligible: false,
    reasonCode: "room_not_in_lobby",
    message: "The activity can start only while the room is in the lobby.",
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
  analysisMode: "placeholder",
};

describe("HostRoomPage", () => {
  beforeEach(() => {
    apiMocks.getRoom.mockResolvedValue(room);
    apiMocks.getSyntheticClassroom.mockResolvedValue({
      enabled: false,
      stage: "answering",
      syntheticParticipantCount: 0,
      pendingSyntheticParticipantCount: 0,
      targetSizes: [],
      canConfigure: false,
      canGenerate: false,
      patternedAvailable: false,
      openRouterAvailable: false,
    });
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

  it("renders coverage truth and auditable answer classifications without optimality theater", async () => {
    apiMocks.getRoom.mockResolvedValue({
      ...room,
      status: "published",
      analysisMode: "coverage_aware",
      analysisPhase: "complete",
      allowedActions: ["viewGroups"],
    });
    apiMocks.getGroups.mockResolvedValue({
      generationMode: "coverage_aware",
      policy: "teach",
      trigger: "all_submitted",
      generatedAt: "2026-07-19T10:01:00.000Z",
      solver: {
        status: "feasible",
        completeCoverageStatus: "unknown",
        timedOut: true,
        solveMilliseconds: 10000,
        objectives: [],
      },
      coverageReport: { fullyCoveredGroupQuestions: 0, totalGroupQuestions: 1 },
      groups: [
        {
          id: "g1",
          members: room.participants,
          questions: [
            {
              questionId: "question-1",
              position: 0,
              prompt: room.questions[0]!.prompt,
              fullyCovered: false,
              units: [
                {
                  id: "unit-1",
                  text: "Defines the dynamic-programming state",
                  covered: true,
                  carriers: [room.participants[0]],
                },
                { id: "unit-2", text: "Explains the recurrence", covered: false, carriers: [] },
              ],
              representedFamilies: [{ id: "f1", label: "Top-down", members: [room.participants[0]] }],
              responseAudit: [
                {
                  participant: room.participants[0],
                  answer: "Let dp[i] describe the best result through i.",
                  coveredUnitIds: ["unit-1"],
                  family: { id: "f1", label: "Top-down" },
                },
              ],
            },
          ],
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Coverage-aware groups" })).toBeInTheDocument();
    expect(screen.getByText(/optimality was not proved/i)).toBeInTheDocument();
    expect(screen.getByText("No submitted answer clearly supported this unit")).toBeInTheDocument();
    expect(screen.getByText("Let dp[i] describe the best result through i.")).toBeInTheDocument();
  });

  it("adds a simulated roster only after the host explicitly submits the lobby control", async () => {
    const user = userEvent.setup();
    const lobbyRoom: HostRoom = {
      ...room,
      status: "lobby",
      activityStarted: false,
      startedAt: null,
      deadlineAt: null,
      remainingSeconds: null,
      progress: { ...room.progress, participantCount: 0, possibleResponseCount: 0 },
      participants: [],
      startEligibility: {
        eligible: false,
        reasonCode: "minimum_participants",
        message: "At least three participants must join.",
      },
      allowedActions: ["startActivity"],
    };
    const projection = {
      enabled: true,
      stage: "lobby" as const,
      syntheticParticipantCount: 0,
      pendingSyntheticParticipantCount: 0,
      targetSizes: [5, 10, 20],
      canConfigure: true,
      canGenerate: false,
      patternedAvailable: true,
      openRouterAvailable: true,
    };
    apiMocks.getRoom.mockResolvedValue(lobbyRoom);
    apiMocks.getSyntheticClassroom
      .mockResolvedValueOnce(projection)
      .mockResolvedValue({ ...projection, syntheticParticipantCount: 20 });
    apiMocks.configureSyntheticCohort.mockResolvedValue({ ...projection, syntheticParticipantCount: 20 });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Simulated participants" })).toBeInTheDocument();
    expect(apiMocks.configureSyntheticCohort).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Simulated roster size"), "20");
    await user.click(screen.getByRole("button", { name: "Add participants" }));

    expect(apiMocks.configureSyntheticCohort).toHaveBeenCalledWith("room-1", { targetSize: 20 });

    await user.click(await screen.findByRole("button", { name: "Remove simulated participants" }));
    expect(apiMocks.configureSyntheticCohort).toHaveBeenLastCalledWith("room-1", { targetSize: 0 });
  });

  it("runs OpenRouter response generation only after an explicit host action", async () => {
    const user = userEvent.setup();
    const projection = {
      enabled: true,
      stage: "answering" as const,
      syntheticParticipantCount: 20,
      pendingSyntheticParticipantCount: 20,
      targetSizes: [],
      canConfigure: false,
      canGenerate: true,
      patternedAvailable: true,
      openRouterAvailable: true,
    };
    apiMocks.getSyntheticClassroom.mockResolvedValue(projection);
    apiMocks.generateSyntheticResponses.mockResolvedValue({
      simulation: { ...projection, pendingSyntheticParticipantCount: 0, canGenerate: false },
      source: "openrouter",
      participantCount: 20,
      responseCount: 20,
      models: ["configured-model"],
    });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Simulated responses" })).toBeInTheDocument();
    expect(apiMocks.generateSyntheticResponses).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Response source"), "openrouter");
    expect(screen.getByText(/answer as distinct student profiles/i)).toBeInTheDocument();
    expect(apiMocks.generateSyntheticResponses).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Generate with OpenRouter and submit" }));

    expect(apiMocks.generateSyntheticResponses).toHaveBeenCalledWith("room-1", { source: "openrouter" });
  });

  it("does not offer OpenRouter when the server has not enabled it", async () => {
    apiMocks.getSyntheticClassroom.mockResolvedValue({
      enabled: true,
      stage: "answering",
      syntheticParticipantCount: 20,
      pendingSyntheticParticipantCount: 20,
      targetSizes: [],
      canConfigure: false,
      canGenerate: true,
      patternedAvailable: true,
      openRouterAvailable: false,
    });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "Patterned local responses" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "OpenRouter responses" })).not.toBeInTheDocument();
  });
});
