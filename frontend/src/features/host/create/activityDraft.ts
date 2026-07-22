import type { GroupingPolicy } from "../../../domain";

export type WizardStep = "material" | "details" | "questions" | "groups" | "review";

export interface QuestionDraft {
  clientId: string;
  prompt: string;
  coverageUnits: string[];
}

export interface ActivityDraft {
  title: string;
  policy: GroupingPolicy;
  durationMinutes: number;
  preferredGroupSize: number;
  materialFile: File | null;
  pastedReference: string;
  questions: QuestionDraft[];
}

export const activitySteps: Array<{ id: WizardStep; label: string }> = [
  { id: "material", label: "Reference material" },
  { id: "details", label: "Activity details" },
  { id: "questions", label: "Questions" },
  { id: "groups", label: "Discussion groups" },
  { id: "review", label: "Review" },
];

export function newQuestionDraft(): QuestionDraft {
  return { clientId: crypto.randomUUID(), prompt: "", coverageUnits: [""] };
}

export function createInitialActivityDraft(): ActivityDraft {
  return {
    title: "",
    policy: "teach",
    durationMinutes: 20,
    preferredGroupSize: 4,
    materialFile: null,
    pastedReference: "",
    questions: [newQuestionDraft()],
  };
}

export function isActivityStepValid(draft: ActivityDraft, candidate: WizardStep): boolean {
  if (candidate === "details") {
    return draft.title.trim().length >= 3 && draft.durationMinutes >= 5;
  }
  if (candidate === "questions") {
    return (
      draft.questions.length > 0 &&
      draft.questions.length <= 8 &&
      draft.questions.every(
        (question) =>
          question.prompt.trim().length >= 5 &&
          question.coverageUnits.length >= 1 &&
          question.coverageUnits.length <= 8 &&
          question.coverageUnits.every((unit) => unit.trim().length >= 3),
      )
    );
  }
  return true;
}
