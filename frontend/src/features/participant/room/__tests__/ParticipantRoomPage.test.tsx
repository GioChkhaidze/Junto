import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ParticipantRoom } from "../../../../domain";
import { ParticipantRoomPage } from "../ParticipantRoomPage";

const apiMocks = vi.hoisted(() => ({
  getParticipantRoom: vi.fn(),
  getRoomStatus: vi.fn(),
  getMyGroup: vi.fn(),
  saveAnswer: vi.fn(),
  submitResponses: vi.fn(),
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

vi.mock("../../../../hooks/useOnlineStatus", () => ({ useOnlineStatus: () => true }));

vi.mock("../../../../hooks/usePolling", () => ({ usePolling: vi.fn() }));

const room: ParticipantRoom = {
  roomId: "room-1",
  title: "Dynamic programming review",
  status: "answering",
  durationMinutes: 20,
  serverTime: "2026-07-20T10:00:00Z",
  startedAt: "2026-07-20T10:00:00Z",
  deadlineAt: "2026-07-20T10:20:00Z",
  remainingSeconds: 1_200,
  activityStarted: true,
  participant: { participantId: "participant-1", displayName: "Maya Chen", submittedAt: null },
  questions: [
    { id: "question-1", position: 0, prompt: "Explain the state used in your solution.", answer: null },
    { id: "question-2", position: 1, prompt: "Derive the recurrence and base case.", answer: null },
  ],
  answeredQuestionCount: 0,
  questionCount: 2,
  allowedActions: ["answer", "submit"],
  submitted: false,
  submittedAt: null,
  analysisPhase: "not_started",
  analysisMode: "placeholder",
};

describe("ParticipantRoomPage answer runner", () => {
  beforeEach(() => {
    apiMocks.getParticipantRoom.mockResolvedValue(room);
    apiMocks.saveAnswer.mockResolvedValue(undefined);
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("saves the current response before moving and updates numbered progress", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/room/room-1"]}>
        <Routes>
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Explain the state used in your solution." }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Question 1, not answered" })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: "Question 2, not answered" })).not.toHaveAttribute("aria-current");

    await user.type(
      screen.getByRole("textbox", { name: "Your response" }),
      "Let state i store the best result for the first i items.",
    );
    await user.click(screen.getByRole("button", { name: "Next question" }));

    await waitFor(() => {
      expect(apiMocks.saveAnswer).toHaveBeenCalledWith("room-1", "question-1", {
        text: "Let state i store the best result for the first i items.",
      });
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Derive the recurrence and base case." }),
    ).toBeInTheDocument();
    const completedQuestion = screen.getByRole("button", { name: "Question 1, answered" });
    expect(completedQuestion).not.toHaveAttribute("aria-current");
    expect(completedQuestion.querySelector("svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Question 2, not answered" })).toHaveAttribute("aria-current", "step");
    expect(screen.getByText("1 answered")).toBeInTheDocument();
    expect(screen.getByText("Saved automatically and before you move between questions.")).toBeInTheDocument();
  });

  it("moves focus to each newly displayed question and the final review", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/room/room-1"]}>
        <Routes>
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { level: 1, name: "Explain the state used in your solution." });
    await user.click(screen.getByRole("button", { name: "Next question" }));

    const secondQuestion = await screen.findByRole("heading", {
      level: 1,
      name: "Derive the recurrence and base case.",
    });
    await waitFor(() => expect(secondQuestion).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Review responses" }));
    const reviewHeading = await screen.findByRole("heading", { level: 1, name: "Review your responses" });
    await waitFor(() => expect(reviewHeading).toHaveFocus());
  });

  it("does not treat Alt-arrow inside the response editor as question navigation", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/room/room-1"]}>
        <Routes>
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const answer = await screen.findByRole("textbox", { name: "Your response" });
    await user.click(answer);
    await user.keyboard("{Alt>}{ArrowRight}{/Alt}");

    expect(answer).toHaveFocus();
    expect(
      screen.getByRole("heading", { level: 1, name: "Explain the state used in your solution." }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 1, name: "Derive the recurrence and base case." }),
    ).not.toBeInTheDocument();
    expect(apiMocks.saveAnswer).not.toHaveBeenCalled();
  });

  it("flushes edits made while an autosave is still in flight before navigating", async () => {
    const user = userEvent.setup();
    let releaseFirstSave!: () => void;
    const firstSave = new Promise<void>((resolve) => {
      releaseFirstSave = resolve;
    });
    apiMocks.saveAnswer.mockReset();
    apiMocks.saveAnswer.mockReturnValueOnce(firstSave).mockResolvedValueOnce(undefined);

    render(
      <MemoryRouter initialEntries={["/room/room-1"]}>
        <Routes>
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const answer = await screen.findByRole("textbox", { name: "Your response" });
    await user.type(answer, "a");
    await waitFor(
      () => {
        expect(apiMocks.saveAnswer).toHaveBeenCalledWith("room-1", "question-1", { text: "a" });
      },
      { timeout: 2200 },
    );

    await user.type(answer, "b");
    await user.click(screen.getByRole("button", { name: "Next question" }));
    expect(
      screen.getByRole("heading", { level: 1, name: "Explain the state used in your solution." }),
    ).toBeInTheDocument();

    await act(async () => {
      releaseFirstSave();
      await firstSave;
    });

    await waitFor(() => {
      expect(apiMocks.saveAnswer).toHaveBeenNthCalledWith(2, "room-1", "question-1", { text: "ab" });
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Derive the recurrence and base case." }),
    ).toBeInTheDocument();
  });

  it("shows only the participant group agenda for a coverage-aware result", async () => {
    const user = userEvent.setup();
    apiMocks.getParticipantRoom.mockResolvedValue({
      ...room,
      status: "published",
      analysisMode: "coverage_aware",
      analysisPhase: "complete",
      allowedActions: ["viewMyGroup"],
    });
    apiMocks.getMyGroup.mockResolvedValue({
      generationMode: "coverage_aware",
      policy: "teach",
      generatedAt: "2026-07-19T10:01:00.000Z",
      completeCoverageStatus: "feasible",
      group: {
        id: "g1",
        members: [
          { participantId: "participant-1", displayName: "Maya Chen" },
          { participantId: "participant-2", displayName: "Alex Kim" },
        ],
        questions: [
          {
            questionId: "question-1",
            position: 0,
            prompt: "Explain the state used in your solution.",
            fullyCovered: true,
            units: [
              {
                id: "unit-1",
                text: "Defines the dynamic-programming state",
                covered: true,
                carriers: [{ participantId: "participant-2", displayName: "Alex Kim" }],
              },
            ],
            representedFamilies: [],
          },
        ],
      },
    });

    render(
      <MemoryRouter initialEntries={["/room/room-1"]}>
        <Routes>
          <Route path="/room/:roomId" element={<ParticipantRoomPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Discussion agenda" })).toBeInTheDocument();
    const questionSummary = screen.getByText("Question 1:").closest("summary");
    const carrierGuidance = screen.getByText("Ask Alex Kim to introduce this idea.");
    expect(questionSummary).not.toBeNull();
    expect(carrierGuidance).not.toBeVisible();
    await user.click(questionSummary!);
    expect(carrierGuidance).toBeVisible();
    expect(screen.queryByText(/answer classifications/i)).not.toBeInTheDocument();
  });
});
