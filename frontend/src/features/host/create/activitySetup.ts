import { api } from "../../../api";
import type { GroupSize, HostQuestion, QuestionMutation, ReferenceAttachment } from "../../../domain";
import type { ActivityDraft, QuestionDraft } from "./activityDraft";

function groupSizeFor(preferred: number): GroupSize {
  return { minimum: Math.max(2, preferred - 1), preferred, maximum: Math.min(8, preferred + 1) };
}

function questionMutation(question: QuestionDraft, position: number): QuestionMutation {
  return {
    position,
    prompt: question.prompt.trim(),
    referenceMaterial: null,
    coverageUnits: question.coverageUnits.map((text) => ({ text: text.trim() })),
  };
}

function questionMatches(existing: HostQuestion, desired: QuestionMutation): boolean {
  return (
    existing.position === desired.position &&
    existing.prompt === desired.prompt &&
    existing.referenceMaterial === (desired.referenceMaterial ?? null) &&
    existing.coverageUnits.length === desired.coverageUnits.length &&
    existing.coverageUnits.every((unit, index) => unit.text === desired.coverageUnits[index]?.text)
  );
}

function materialMatches(file: File, material: ReferenceAttachment): boolean {
  return file.name === material.fileName && file.size === material.sizeBytes;
}

function referenceFile(draft: ActivityDraft, skipReference: boolean): File | null {
  if (skipReference) return null;
  if (draft.materialFile) return draft.materialFile;
  const pastedReference = draft.pastedReference.trim();
  return pastedReference ? new File([pastedReference], "pasted-reference.txt", { type: "text/plain" }) : null;
}

/** Owns the resumable browser-side protocol for creating, reconciling, and opening one activity. */
export class ActivitySetupSession {
  private roomId: string | null = null;

  get hasDraftRoom(): boolean {
    return this.roomId !== null;
  }

  async saveAndOpen(draft: ActivityDraft, options: { skipReference: boolean }): Promise<string> {
    let savedRoom = this.roomId ? await api.getRoom(this.roomId) : null;
    if (savedRoom && savedRoom.status !== "draft") {
      return savedRoom.id;
    }

    if (this.roomId === null) {
      const created = await api.createRoom({
        title: draft.title.trim(),
        policy: draft.policy,
        groupSize: groupSizeFor(draft.preferredGroupSize),
        durationMinutes: draft.durationMinutes,
      });
      this.roomId = created.roomId;
    } else if (savedRoom) {
      const desiredGroupSize = groupSizeFor(draft.preferredGroupSize);
      const settingsChanged =
        savedRoom.title !== draft.title.trim() ||
        savedRoom.durationMinutes !== draft.durationMinutes ||
        savedRoom.policy !== draft.policy ||
        savedRoom.groupSize.minimum !== desiredGroupSize.minimum ||
        savedRoom.groupSize.preferred !== desiredGroupSize.preferred ||
        savedRoom.groupSize.maximum !== desiredGroupSize.maximum;
      if (settingsChanged) {
        savedRoom = await api.updateRoom(this.roomId, {
          title: draft.title.trim(),
          policy: draft.policy,
          groupSize: desiredGroupSize,
          durationMinutes: draft.durationMinutes,
        });
      }
    }

    const roomId = this.roomId;
    const existingQuestions = [...(savedRoom?.questions ?? [])].sort((left, right) => left.position - right.position);
    for (const extra of existingQuestions.slice(draft.questions.length).reverse()) {
      await api.deleteQuestion(roomId, extra.id);
    }
    for (const [position, question] of draft.questions.entries()) {
      const mutation = questionMutation(question, position);
      const existing = existingQuestions[position];
      if (!existing) {
        await api.createQuestion(roomId, mutation);
      } else if (!questionMatches(existing, mutation)) {
        await api.updateQuestion(roomId, existing.id, mutation);
      }
    }

    const desiredReference = referenceFile(draft, options.skipReference);
    if (desiredReference) {
      const matchingMaterial = savedRoom?.materials.find((material) => materialMatches(desiredReference, material));
      for (const material of savedRoom?.materials ?? []) {
        if (material.id !== matchingMaterial?.id) {
          await api.deleteReferenceMaterial(roomId, material.id);
        }
      }
      if (!matchingMaterial) await api.uploadReferenceMaterial(roomId, desiredReference);
    } else {
      for (const material of savedRoom?.materials ?? []) {
        await api.deleteReferenceMaterial(roomId, material.id);
      }
    }

    await api.openRoom(roomId);
    return roomId;
  }
}
