import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateRoomPage } from "../CreateRoomPage";

const apiMocks = vi.hoisted(() => ({
  createRoom: vi.fn(),
  getRoom: vi.fn(),
  createQuestion: vi.fn(),
  updateQuestion: vi.fn(),
  deleteQuestion: vi.fn(),
  updateRoom: vi.fn(),
  uploadReferenceMaterial: vi.fn(),
  deleteReferenceMaterial: vi.fn(),
  openRoom: vi.fn(),
}));

vi.mock("../../../../api", () => ({
  api: apiMocks,
  ApiError: class ApiError extends Error {},
}));

describe("CreateRoomPage", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("begins with optional reference material before activity details", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);

    render(
      <MemoryRouter initialEntries={["/create"]}>
        <CreateRoomPage />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "Add reference material" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Attach a reading, rubric, notes, or answer guide/i),
    ).toHaveTextContent("Optional");
    const fileInput = screen.getByLabelText("Choose file", {
      selector: 'input[type="file"]',
    }) as HTMLInputElement;
    expect(fileInput.labels).toHaveLength(1);
    expect(fileInput.labels?.[0]).toBeVisible();
    expect(fileInput.labels?.[0]).toHaveTextContent("Choose file");
    expect(screen.queryByRole("button", { name: "Choose file" })).not.toBeInTheDocument();
    expect(screen.getByText("Paste reference text instead")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Continue without material" }));

    const detailsHeading = screen.getByRole("heading", {
      level: 1,
      name: "Set up the activity",
    });
    await waitFor(() => expect(detailsHeading).toHaveFocus());
  });

  it("resumes a partially created room without duplicating a question", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    apiMocks.createRoom.mockResolvedValue({
      roomId: "room-1",
      joinCode: "J7KM4P",
      status: "draft",
    });
    apiMocks.createQuestion.mockRejectedValueOnce(new Error("Connection interrupted"));
    apiMocks.getRoom.mockResolvedValue({
      id: "room-1",
      joinCode: "J7KM4P",
      title: "Seminar review",
      policy: "teach",
      groupSize: { minimum: 3, preferred: 4, maximum: 5 },
      durationMinutes: 20,
      status: "draft",
      questions: [
        {
          id: "question-1",
          position: 0,
          prompt: "Compare the two arguments.",
          referenceMaterial: null,
          coverageUnits: [{ id: "unit-1", text: "Explains the central objection" }],
        },
      ],
      materials: [],
      participants: [],
      progress: {
        participantCount: 0,
        submittedParticipantCount: 0,
        answeredResponseCount: 0,
        submittedResponseCount: 0,
        possibleResponseCount: 0,
      },
      allowedActions: ["editRoom"],
      analysisPhase: "not_started",
      lastError: null,
    });
    apiMocks.openRoom.mockResolvedValue({ status: "lobby" });

    render(
      <MemoryRouter initialEntries={["/create"]}>
        <CreateRoomPage />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "Continue without material" }));
    await user.type(screen.getByRole("textbox", { name: /Activity title/i }), "Seminar review");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(
      screen.getByRole("textbox", { name: "Question prompt" }),
      "Compare the two arguments.",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Coverage unit 1 for question 1" }),
      "Explains the central objection",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Create activity" }));

    expect(await screen.findByText("Connection interrupted")).toBeInTheDocument();
    expect(apiMocks.createRoom).toHaveBeenCalledTimes(1);
    expect(apiMocks.createQuestion).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Retry setup" }));

    await waitFor(() => expect(apiMocks.openRoom).toHaveBeenCalledTimes(1));
    expect(apiMocks.createRoom).toHaveBeenCalledTimes(1);
    expect(apiMocks.createQuestion).toHaveBeenCalledTimes(1);
    expect(apiMocks.updateQuestion).not.toHaveBeenCalled();
  });

  it("lets the host correct a saved draft and reconciles removed questions", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    const savedRoom = {
      id: "room-1",
      joinCode: "J7KM4P",
      title: "Original seminar",
      policy: "teach",
      groupSize: { minimum: 3, preferred: 4, maximum: 5 },
      durationMinutes: 20,
      status: "draft",
      questions: [
        {
          id: "question-1",
          position: 0,
          prompt: "Compare the two arguments.",
          referenceMaterial: null,
          coverageUnits: [{ id: "unit-1", text: "Explains the central objection" }],
        },
        {
          id: "question-2",
          position: 1,
          prompt: "Which argument is stronger?",
          referenceMaterial: null,
          coverageUnits: [{ id: "unit-2", text: "Defends a reasoned conclusion" }],
        },
      ],
      materials: [],
      participants: [],
      progress: {
        participantCount: 0,
        submittedParticipantCount: 0,
        answeredResponseCount: 0,
        submittedResponseCount: 0,
        possibleResponseCount: 0,
      },
      allowedActions: ["editRoom"],
      analysisPhase: "not_started",
      lastError: null,
    };
    apiMocks.createRoom.mockResolvedValue({
      roomId: "room-1",
      joinCode: "J7KM4P",
      status: "draft",
    });
    apiMocks.createQuestion.mockResolvedValue({});
    apiMocks.openRoom
      .mockRejectedValueOnce(new Error("Lobby could not open"))
      .mockResolvedValueOnce({ status: "lobby" });
    apiMocks.getRoom.mockResolvedValue(savedRoom);
    apiMocks.updateRoom.mockResolvedValue({
      ...savedRoom,
      title: "Corrected seminar",
    });
    apiMocks.deleteQuestion.mockResolvedValue(undefined);
    apiMocks.updateQuestion.mockResolvedValue({});

    render(
      <MemoryRouter initialEntries={["/create"]}>
        <CreateRoomPage />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "Continue without material" }));
    await user.type(screen.getByRole("textbox", { name: /Activity title/i }), "Original seminar");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByRole("textbox", { name: "Question prompt" }), "Compare the two arguments.");
    await user.type(
      screen.getByRole("textbox", { name: "Coverage unit 1 for question 1" }),
      "Explains the central objection",
    );
    await user.click(screen.getByRole("button", { name: "Add another question" }));
    await user.type(
      screen.getAllByRole("textbox", { name: "Question prompt" })[1]!,
      "Which argument is stronger?",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Coverage unit 1 for question 2" }),
      "Defends a reasoned conclusion",
    );
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Create activity" }));

    expect(await screen.findByText("Lobby could not open")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(screen.getByRole("button", { name: "Delete question 2" }));
    const firstPrompt = screen.getByRole("textbox", { name: "Question prompt" });
    await user.clear(firstPrompt);
    await user.type(firstPrompt, "Compare the strongest two arguments.");
    await user.click(screen.getByRole("button", { name: "Back" }));
    const title = screen.getByRole("textbox", { name: /Activity title/i });
    await user.clear(title);
    await user.type(title, "Corrected seminar");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Retry setup" }));

    await waitFor(() => expect(apiMocks.openRoom).toHaveBeenCalledTimes(2));
    expect(apiMocks.createRoom).toHaveBeenCalledTimes(1);
    expect(apiMocks.updateRoom).toHaveBeenCalledWith("room-1", {
      title: "Corrected seminar",
      policy: "teach",
      groupSize: { minimum: 3, preferred: 4, maximum: 5 },
      durationMinutes: 20,
    });
    expect(apiMocks.deleteQuestion).toHaveBeenCalledWith("room-1", "question-2");
    expect(apiMocks.updateQuestion).toHaveBeenCalledWith("room-1", "question-1", {
      position: 0,
      prompt: "Compare the strongest two arguments.",
      referenceMaterial: null,
      coverageUnits: [{ text: "Explains the central objection" }],
    });
    expect(apiMocks.createQuestion).toHaveBeenCalledTimes(2);
  });
});
