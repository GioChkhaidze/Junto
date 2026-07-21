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
      syntheticParticipantIds: [],
      pendingSyntheticParticipantIds: [],
      generation: null,
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

    expect(screen.getByRole("link", { name: "Activities" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy host link" })).not.toBeInTheDocument();
    expect(liveAncestor).toBeNull();
  });

  it("reveals coverage, family placement, and numbered answer classifications in layers", async () => {
    const user = userEvent.setup();
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

    expect(await screen.findByRole("heading", { name: "Groups" })).toBeInTheDocument();
    expect(screen.getByText(/complete-coverage feasibility was not resolved/i)).toBeInTheDocument();
    expect(screen.queryByText("Defines the dynamic-programming state")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Group 1: Maya Chen, Alex Kim, Sam Lee, Noor Ali/ }));
    await user.click(screen.getByRole("button", { name: /Question 1: Explain the state used in your solution/ }));

    expect(screen.getByText("Supported by Maya Chen")).toBeInTheDocument();
    expect(screen.getByText("Not represented in this group")).toBeInTheDocument();
    expect(screen.getByText("Top-down")).toBeInTheDocument();
    expect(screen.getByText("Maya Chen")).toBeInTheDocument();
    expect(screen.queryByText("Let dp[i] describe the best result through i.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show answer classifications" }));

    expect(screen.getByText("Covered units: 1")).toBeInTheDocument();
    expect(screen.getByText("Let dp[i] describe the best result through i.")).toBeInTheDocument();
    expect(screen.getAllByText("Defines the dynamic-programming state")).toHaveLength(1);
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
    expect(screen.getByText(/activity title, question prompts, anonymous behavioral profiles/i)).toBeInTheDocument();
    expect(screen.getByText(/uploaded or pasted room-wide source text/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Participant names and IDs, coverage units, and host-only notes are not sent/i),
    ).toBeInTheDocument();
    expect(apiMocks.configureSyntheticCohort).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText("Simulated roster size"), "20");
    await user.click(screen.getByRole("button", { name: "Add participants" }));

    expect(apiMocks.configureSyntheticCohort).toHaveBeenCalledWith("room-1", { targetSize: 20 });

    await user.click(await screen.findByRole("button", { name: "Remove simulated participants" }));
    expect(apiMocks.configureSyntheticCohort).toHaveBeenLastCalledWith("room-1", { targetSize: 0 });
  });

  it("does not let an unavailable provider strand a simulated roster after the room starts", async () => {
    const user = userEvent.setup();
    const lobbyRoom: HostRoom = {
      ...room,
      status: "lobby",
      activityStarted: false,
      startedAt: null,
      deadlineAt: null,
      remainingSeconds: null,
      startEligibility: { eligible: true, reasonCode: null, message: "The room is ready to start." },
      allowedActions: ["startActivity"],
    };
    const projection = {
      enabled: true,
      stage: "lobby" as const,
      syntheticParticipantCount: 5,
      pendingSyntheticParticipantCount: 0,
      targetSizes: [5, 10, 20],
      canConfigure: true,
      canGenerate: false,
      patternedAvailable: true,
      openRouterAvailable: false,
    };
    apiMocks.getRoom.mockResolvedValue(lobbyRoom);
    apiMocks.getSyntheticClassroom.mockResolvedValue(projection);
    apiMocks.configureSyntheticCohort.mockResolvedValue({ ...projection, syntheticParticipantCount: 0 });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Remove this simulated roster before starting/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Simulated roster size")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Update participants" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start activity" })).toBeDisabled();
    expect(screen.getByText(/Remove the simulated roster or configure OpenRouter/i)).toBeInTheDocument();

    const removeButton = screen.getByRole("button", { name: "Remove simulated participants" });
    expect(removeButton).toBeEnabled();
    await user.click(removeButton);
    expect(apiMocks.configureSyntheticCohort).toHaveBeenCalledWith("room-1", { targetSize: 0 });
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
    expect(screen.getByText(/activity title, question prompts, anonymous behavioral profiles/i)).toBeInTheDocument();
    expect(screen.getByText(/uploaded or pasted room-wide source text/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Participant names and IDs, coverage units, and host-only notes are not sent/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Generated responses can be incomplete or mistaken/i)).toBeInTheDocument();
    expect(screen.queryByText(/patterned local responses/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Response source")).not.toBeInTheDocument();
    expect(apiMocks.generateSyntheticResponses).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Generate with OpenRouter and submit" }));

    expect(apiMocks.generateSyntheticResponses).toHaveBeenCalledWith("room-1", { source: "openrouter" });
    expect(await screen.findByText("Simulated responses submitted")).toBeInTheDocument();
    expect(screen.getByText(/20 question responses through OpenRouter/i)).toBeInTheDocument();
    expect(screen.getByText(/Models: configured-model/i)).toBeInTheDocument();
  });

  it("shows per-student OpenRouter statuses without duplicating the room progress", async () => {
    const partialRoom: HostRoom = {
      ...room,
      progress: { ...room.progress, submittedParticipantCount: 1, answeredResponseCount: 1, submittedResponseCount: 1 },
      participants: [
        { ...room.participants[0]!, submittedAt: "2026-07-19T10:00:10.000Z" },
        ...room.participants.slice(1),
      ],
    };
    apiMocks.getRoom.mockResolvedValue(partialRoom);
    apiMocks.getSyntheticClassroom.mockResolvedValue({
      enabled: true,
      stage: "answering",
      syntheticParticipantCount: 4,
      pendingSyntheticParticipantCount: 3,
      targetSizes: [],
      canConfigure: false,
      canGenerate: false,
      patternedAvailable: false,
      openRouterAvailable: true,
      syntheticParticipantIds: room.participants.map((participant) => participant.participantId),
      pendingSyntheticParticipantIds: room.participants.slice(1).map((participant) => participant.participantId),
      generation: {
        status: "running",
        source: "openrouter",
        requestedParticipantCount: 4,
        completedParticipantCount: 1,
        failedParticipantCount: 0,
        startedAt: "2026-07-19T10:00:00.000Z",
        finishedAt: null,
        error: null,
      },
    });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Submitted")).toBeInTheDocument();
    expect(screen.getAllByText("Generating")).toHaveLength(3);
    expect(
      screen.queryByRole("progressbar", { name: "Simulated response generation progress" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Working")).not.toBeInTheDocument();
  });

  it("keeps partial simulated submissions and offers a retry for only the remaining students", async () => {
    apiMocks.getSyntheticClassroom.mockResolvedValue({
      enabled: true,
      stage: "answering",
      syntheticParticipantCount: 4,
      pendingSyntheticParticipantCount: 3,
      targetSizes: [],
      canConfigure: false,
      canGenerate: true,
      patternedAvailable: false,
      openRouterAvailable: true,
      syntheticParticipantIds: room.participants.map((participant) => participant.participantId),
      pendingSyntheticParticipantIds: room.participants.slice(1).map((participant) => participant.participantId),
      generation: {
        status: "failed",
        source: "openrouter",
        requestedParticipantCount: 4,
        completedParticipantCount: 1,
        failedParticipantCount: 3,
        startedAt: "2026-07-19T10:00:00.000Z",
        finishedAt: "2026-07-19T10:00:20.000Z",
        error:
          "OpenRouter stopped after 1 simulated participant submitted. Their responses were kept; retry the " +
          "remaining participants.",
      },
    });

    render(
      <MemoryRouter initialEntries={["/host/room-1"]}>
        <Routes>
          <Route path="/host/:roomId" element={<HostRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "Retry remaining students" })).toBeEnabled();
    expect(screen.getAllByText("Needs retry")).toHaveLength(3);
    expect(screen.getByRole("alert")).toHaveTextContent(/responses were kept/i);
  });

  it("fails closed instead of offering patterned fillers when OpenRouter is unavailable", async () => {
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

    expect(await screen.findByRole("heading", { name: "Response generation unavailable" })).toBeInTheDocument();
    expect(screen.getByText(/will not submit placeholder answers/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/patterned local responses/i)).not.toBeInTheDocument();
    expect(apiMocks.generateSyntheticResponses).not.toHaveBeenCalled();
  });
});
