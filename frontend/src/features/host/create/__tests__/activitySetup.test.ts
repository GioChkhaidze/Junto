import { describe, expect, it, vi } from "vitest";
import { createInitialActivityDraft } from "../activityDraft";
import { ActivitySetupSession } from "../activitySetup";

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

vi.mock("../../../../api", () => ({ api: apiMocks }));

describe("ActivitySetupSession", () => {
  it("retains a created draft and reconciles it without duplicating questions after a retry", async () => {
    const draft = createInitialActivityDraft();
    draft.title = "Seminar review";
    draft.questions[0] = {
      ...draft.questions[0]!,
      prompt: "Compare the two arguments.",
      coverageUnits: ["Explains the central objection"],
    };

    apiMocks.createRoom.mockResolvedValue({ roomId: "room-1", joinCode: "J7KM4P", status: "draft" });
    apiMocks.createQuestion.mockRejectedValueOnce(new Error("Connection interrupted"));

    const setup = new ActivitySetupSession();
    await expect(setup.saveAndOpen(draft, { skipReference: false })).rejects.toThrow("Connection interrupted");
    expect(setup.hasDraftRoom).toBe(true);

    apiMocks.getRoom.mockResolvedValue({
      id: "room-1",
      status: "draft",
      title: draft.title,
      durationMinutes: draft.durationMinutes,
      policy: draft.policy,
      groupSize: { minimum: 3, preferred: 4, maximum: 5 },
      questions: [
        {
          id: "question-1",
          position: 0,
          prompt: draft.questions[0]!.prompt,
          referenceMaterial: null,
          coverageUnits: [{ id: "unit-1", text: draft.questions[0]!.coverageUnits[0] }],
        },
      ],
      materials: [],
    });
    apiMocks.openRoom.mockResolvedValue({ status: "lobby" });

    await expect(setup.saveAndOpen(draft, { skipReference: false })).resolves.toBe("room-1");
    expect(apiMocks.createRoom).toHaveBeenCalledTimes(1);
    expect(apiMocks.createQuestion).toHaveBeenCalledTimes(1);
    expect(apiMocks.updateQuestion).not.toHaveBeenCalled();
    expect(apiMocks.openRoom).toHaveBeenCalledWith("room-1");
  });
});
