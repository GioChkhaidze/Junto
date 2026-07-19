import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell } from "../../../components/layout";
import {
  Button,
  Field,
  Icon,
  InlineNotice,
  Input,
  Select,
  TextArea,
} from "../../../components/ui";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { formatDuration, formatFileSize } from "../../../lib/format";
import { scrollPageToTop } from "../../../lib/motion";
import type { GroupSize, HostQuestion, QuestionMutation, ReferenceAttachment } from "../../../domain";
import styles from "./CreateRoomPage.module.css";

type WizardStep = "material" | "details" | "questions" | "review";

interface QuestionDraft {
  clientId: string;
  prompt: string;
  coverageUnits: string[];
}

interface ActivityDraft {
  title: string;
  durationMinutes: number;
  preferredGroupSize: number;
  materialFile: File | null;
  pastedReference: string;
  questions: QuestionDraft[];
}

const steps: Array<{ id: WizardStep; label: string }> = [
  { id: "material", label: "Reference material" },
  { id: "details", label: "Activity details" },
  { id: "questions", label: "Questions" },
  { id: "review", label: "Review" },
];

const acceptedTypes = ".pdf,.docx,.txt,.md";
const acceptedExtensions = [".pdf", ".docx", ".txt", ".md"];
const maxFileBytes = 5 * 1024 * 1024;

function newQuestion(): QuestionDraft {
  return { clientId: crypto.randomUUID(), prompt: "", coverageUnits: [""] };
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Junto couldn’t create the activity. Please try again.";
}

function groupSizeFor(preferred: number): GroupSize {
  return {
    minimum: Math.max(2, preferred - 1),
    preferred,
    maximum: Math.min(8, preferred + 1),
  };
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
    existing.coverageUnits.every(
      (unit, index) => unit.text === desired.coverageUnits[index]?.text,
    )
  );
}

function materialMatches(file: File, material: ReferenceAttachment): boolean {
  return file.name === material.fileName && file.size === material.sizeBytes;
}

function ReferenceFilePicker({
  describedBy,
  label,
  onChange,
}: {
  describedBy: string;
  label: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <span className={styles.filePicker}>
      <input
        id="reference-material-file"
        className={styles.filePickerInput}
        type="file"
        accept={acceptedTypes}
        onChange={onChange}
        aria-describedby={describedBy}
      />
      <label className={styles.filePickerLabel} htmlFor="reference-material-file">
        {label}
      </label>
    </span>
  );
}

export function CreateRoomPage() {
  useDocumentTitle("Create an activity");
  const navigate = useNavigate();
  const stepHeadingRef = useRef<HTMLHeadingElement>(null);
  const [step, setStep] = useState<WizardStep>("material");
  const [dragging, setDragging] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [setupRoomId, setSetupRoomId] = useState<string | null>(null);
  const [skipReference, setSkipReference] = useState(false);
  const [draft, setDraft] = useState<ActivityDraft>({
    title: "",
    durationMinutes: 20,
    preferredGroupSize: 4,
    materialFile: null,
    pastedReference: "",
    questions: [newQuestion()],
  });

  const activeIndex = steps.findIndex((item) => item.id === step);

  useEffect(() => {
    stepHeadingRef.current?.focus({ preventScroll: true });
    scrollPageToTop();
  }, [step]);

  function updateDraft<K extends keyof ActivityDraft>(key: K, value: ActivityDraft[K]) {
    setSubmitError(null);
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function setMaterial(file: File | null) {
    setFileError(null);
    if (!file) {
      updateDraft("materialFile", null);
      return;
    }
    if (!acceptedExtensions.some((extension) => file.name.toLowerCase().endsWith(extension))) {
      setFileError("Choose a PDF, DOCX, text, or Markdown file.");
      return;
    }
    if (file.size > maxFileBytes) {
      setFileError("Choose a file smaller than 5 MB.");
      return;
    }
    setSkipReference(false);
    updateDraft("pastedReference", "");
    updateDraft("materialFile", file);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setMaterial(event.target.files?.[0] ?? null);
    event.target.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    setMaterial(event.dataTransfer.files?.[0] ?? null);
  }

  function updateQuestion(clientId: string, prompt: string) {
    updateDraft(
      "questions",
      draft.questions.map((question) =>
        question.clientId === clientId ? { ...question, prompt } : question,
      ),
    );
  }

  function updateCoverageUnit(clientId: string, unitIndex: number, text: string) {
    updateDraft(
      "questions",
      draft.questions.map((question) => {
        if (question.clientId !== clientId) return question;
        const coverageUnits = [...question.coverageUnits];
        coverageUnits[unitIndex] = text;
        return { ...question, coverageUnits };
      }),
    );
  }

  function addCoverageUnit(clientId: string) {
    updateDraft(
      "questions",
      draft.questions.map((question) =>
        question.clientId === clientId && question.coverageUnits.length < 8
          ? { ...question, coverageUnits: [...question.coverageUnits, ""] }
          : question,
      ),
    );
  }

  function removeCoverageUnit(clientId: string, unitIndex: number) {
    updateDraft(
      "questions",
      draft.questions.map((question) =>
        question.clientId === clientId && question.coverageUnits.length > 1
          ? {
              ...question,
              coverageUnits: question.coverageUnits.filter((_, index) => index !== unitIndex),
            }
          : question,
      ),
    );
  }

  function removeQuestion(clientId: string) {
    if (draft.questions.length === 1) return;
    updateDraft(
      "questions",
      draft.questions.filter((question) => question.clientId !== clientId),
    );
  }

  function moveQuestion(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= draft.questions.length) return;
    const questions = [...draft.questions];
    const current = questions[index];
    const adjacent = questions[target];
    if (!current || !adjacent) return;
    questions[index] = adjacent;
    questions[target] = current;
    updateDraft("questions", questions);
  }

  function isStepValid(candidate: WizardStep): boolean {
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

  function next() {
    const currentIndex = steps.findIndex((item) => item.id === step);
    const nextStep = steps[currentIndex + 1];
    if (!nextStep || !isStepValid(step)) return;
    setStep(nextStep.id);
  }

  function previous() {
    const currentIndex = steps.findIndex((item) => item.id === step);
    const previousStep = steps[currentIndex - 1];
    if (!previousStep) return;
    setStep(previousStep.id);
  }

  async function createActivity(event: FormEvent) {
    event.preventDefault();
    if (!isStepValid("details") || !isStepValid("questions")) return;
    setCreating(true);
    setSubmitError(null);
    let roomId = setupRoomId;

    try {
      let savedRoom = roomId ? await api.getRoom(roomId) : null;
      if (savedRoom && savedRoom.status !== "draft") {
        navigate(`/host/${roomId}`, { replace: true });
        return;
      }

      if (!roomId) {
        const created = await api.createRoom({
          title: draft.title.trim(),
          policy: "teach",
          groupSize: groupSizeFor(draft.preferredGroupSize),
          durationMinutes: draft.durationMinutes,
        });
        roomId = created.roomId;
        setSetupRoomId(roomId);
      } else if (savedRoom) {
        const desiredGroupSize = groupSizeFor(draft.preferredGroupSize);
        const settingsChanged =
          savedRoom.title !== draft.title.trim() ||
          savedRoom.durationMinutes !== draft.durationMinutes ||
          savedRoom.policy !== "teach" ||
          savedRoom.groupSize.minimum !== desiredGroupSize.minimum ||
          savedRoom.groupSize.preferred !== desiredGroupSize.preferred ||
          savedRoom.groupSize.maximum !== desiredGroupSize.maximum;
        if (settingsChanged) {
          savedRoom = await api.updateRoom(roomId, {
            title: draft.title.trim(),
            policy: "teach",
            groupSize: desiredGroupSize,
            durationMinutes: draft.durationMinutes,
          });
        }
      }

      const existingQuestions = [...(savedRoom?.questions ?? [])].sort(
        (left, right) => left.position - right.position,
      );
      for (const extra of existingQuestions.slice(draft.questions.length).reverse()) {
        await api.deleteQuestion(roomId, extra.id);
      }
      for (const [position, question] of draft.questions.entries()) {
        const mutation = questionMutation(question, position);
        const existing = existingQuestions[position];
        if (existing) {
          if (!questionMatches(existing, mutation)) {
            await api.updateQuestion(roomId, existing.id, mutation);
          }
        } else {
          await api.createQuestion(roomId, mutation);
        }
      }

      const referenceFile = skipReference
        ? null
        : draft.materialFile ??
          (draft.pastedReference.trim()
            ? new File([draft.pastedReference.trim()], "pasted-reference.txt", {
                type: "text/plain",
              })
            : null);
      if (referenceFile) {
        const matchingMaterial = savedRoom?.materials.find((material) =>
          materialMatches(referenceFile, material),
        );
        for (const material of savedRoom?.materials ?? []) {
          if (material.id !== matchingMaterial?.id) {
            await api.deleteReferenceMaterial(roomId, material.id);
          }
        }
        if (!matchingMaterial) await api.uploadReferenceMaterial(roomId, referenceFile);
      } else {
        for (const material of savedRoom?.materials ?? []) {
          await api.deleteReferenceMaterial(roomId, material.id);
        }
      }

      await api.openRoom(roomId);
      navigate(`/host/${roomId}`, { replace: true, state: { newlyCreated: true } });
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      setCreating(false);
    }
  }

  return (
    <AppShell context="Create an activity" wide>
      <div className={styles.createLayout}>
        <aside className={styles.stepRail} aria-label="Create activity progress">
          <ol>
            {steps.map((item, index) => {
              const completed = index < activeIndex;
              const current = item.id === step;
              return (
                <li key={item.id} className={current ? styles.currentStep : ""}>
                  <button
                    type="button"
                    onClick={() => completed && setStep(item.id)}
                    disabled={!completed || creating}
                    aria-current={current ? "step" : undefined}
                  >
                    <span className={styles.stepNumber} aria-hidden="true">
                      {completed ? <Icon name="check" size={15} /> : index + 1}
                    </span>
                    <span>{item.label}</span>
                  </button>
                </li>
              );
            })}
          </ol>
          <p>
            {setupRoomId
              ? "Your room draft is saved. Changes are reconciled when you retry setup."
              : "Your draft is created only after you review everything."}
          </p>
        </aside>

        <form className={styles.form} onSubmit={createActivity}>
          {step === "material" ? (
            <section aria-labelledby="material-title">
              <header className={styles.sectionHeader}>
                <div>
                  <h1 id="material-title" ref={stepHeadingRef} tabIndex={-1}>Add reference material</h1>
                  <p>
                    Optional. Attach a reading, rubric, notes, or answer guide to this room.
                    Participants won’t see the file, and placeholder grouping does not read it.
                  </p>
                </div>
                <span className={styles.optionalText}>Optional</span>
              </header>

              <div
                className={`${styles.uploadArea} ${dragging ? styles.uploadDragging : ""}`}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  if (event.currentTarget === event.target) setDragging(false);
                }}
                onDrop={onDrop}
              >
                {draft.materialFile ? (
                  <div className={styles.fileRow}>
                    <Icon name="file" size={22} />
                    <div id="selected-material-file-help">
                      <strong>{draft.materialFile.name}</strong>
                      <span>{formatFileSize(draft.materialFile.size)}</span>
                    </div>
                    <ReferenceFilePicker
                      label="Replace"
                      describedBy="selected-material-file-help"
                      onChange={onFileChange}
                    />
                    <Button
                      type="button"
                      variant="quiet"
                      size="compact"
                      leadingIcon={<Icon name="trash" size={16} />}
                      onClick={() => setMaterial(null)}
                    >
                      Remove
                    </Button>
                  </div>
                ) : (
                  <div className={styles.uploadPrompt}>
                    <Icon name="upload" size={24} />
                    <div>
                      <strong>Drop a file here or choose from your computer</strong>
                      <span id="material-file-help">PDF, DOCX, text, or Markdown · 5 MB maximum</span>
                    </div>
                    <ReferenceFilePicker
                      label="Choose file"
                      describedBy="material-file-help"
                      onChange={onFileChange}
                    />
                  </div>
                )}
              </div>
              {fileError ? (
                <InlineNotice tone="error" title="File not added">
                  {fileError}
                </InlineNotice>
              ) : null}

              <details className={styles.pasteOption}>
                <summary>Paste reference text instead</summary>
                <Field
                  label="Reference text"
                  hint="Use this for a short rubric, key, or excerpt. It remains host-only."
                >
                  <TextArea
                    rows={8}
                    maxLength={8000}
                    value={draft.pastedReference}
                    onChange={(event) => {
                      setSkipReference(false);
                      if (event.target.value) updateDraft("materialFile", null);
                      updateDraft("pastedReference", event.target.value);
                    }}
                    placeholder="Paste host-only context here…"
                  />
                </Field>
              </details>
            </section>
          ) : null}

          {step === "details" ? (
            <section aria-labelledby="details-title">
              <header className={styles.sectionHeader}>
                <div>
                  <h1 id="details-title" ref={stepHeadingRef} tabIndex={-1}>Set up the activity</h1>
                  <p>Give participants enough context to recognize the room, then set one shared response window.</p>
                </div>
              </header>
              <div className={styles.fieldStack}>
                <Field
                  label="Activity title"
                  hint="Shown on the join page and throughout the activity."
                  error={draft.title.length > 0 && draft.title.trim().length < 3 ? "Use at least 3 characters." : undefined}
                  required
                >
                  <Input
                    maxLength={120}
                    value={draft.title}
                    onChange={(event) => updateDraft("title", event.target.value)}
                    placeholder="e.g. Ethics seminar: responsibility"
                  />
                </Field>

                <div className={styles.twoColumns}>
                  <Field
                    label="Response time"
                    hint="The countdown begins when you start the activity."
                    required
                  >
                    <Select
                      value={draft.durationMinutes}
                      onChange={(event) => updateDraft("durationMinutes", Number(event.target.value))}
                    >
                      {[5, 10, 15, 20, 25, 30, 45, 60].map((minutes) => (
                        <option key={minutes} value={minutes}>
                          {formatDuration(minutes)}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field
                    label="Preferred group size"
                    hint="Junto may vary groups by one person to include everyone."
                    required
                  >
                    <Select
                      value={draft.preferredGroupSize}
                      onChange={(event) => updateDraft("preferredGroupSize", Number(event.target.value))}
                    >
                      {[3, 4, 5, 6, 7].map((size) => (
                        <option key={size} value={size}>
                          {size} people
                        </option>
                      ))}
                    </Select>
                  </Field>
                </div>
              </div>
            </section>
          ) : null}

          {step === "questions" ? (
            <section aria-labelledby="questions-title">
              <header className={styles.sectionHeader}>
                <div>
                  <h1 id="questions-title" ref={stepHeadingRef} tabIndex={-1}>Write the questions</h1>
                  <p>
                    Participants answer one question at a time. Use complete prompts and include any reading they must see directly in the question.
                  </p>
                </div>
              </header>

              <div className={styles.questionList}>
                {draft.questions.map((question, index) => (
                  <article className={styles.questionEditor} key={question.clientId}>
                    <header>
                      <h2>Question {index + 1}</h2>
                      <div className={styles.questionActions}>
                        <Button
                          type="button"
                          variant="quiet"
                          size="compact"
                          onClick={() => moveQuestion(index, -1)}
                          disabled={index === 0}
                          aria-label={`Move question ${index + 1} earlier`}
                        >
                          Move up
                        </Button>
                        <Button
                          type="button"
                          variant="quiet"
                          size="compact"
                          onClick={() => moveQuestion(index, 1)}
                          disabled={index === draft.questions.length - 1}
                          aria-label={`Move question ${index + 1} later`}
                        >
                          Move down
                        </Button>
                        <Button
                          type="button"
                          variant="quiet"
                          size="compact"
                          onClick={() => removeQuestion(question.clientId)}
                          disabled={draft.questions.length === 1}
                          aria-label={`Delete question ${index + 1}`}
                          leadingIcon={<Icon name="trash" size={16} />}
                        >
                          Delete
                        </Button>
                      </div>
                    </header>
                    <Field
                      label="Question prompt"
                      hint={`${question.prompt.length.toLocaleString()} of 2,000 characters · all questions share the room timer`}
                      error={question.prompt.length > 0 && question.prompt.trim().length < 5 ? "Write a complete question." : undefined}
                      required
                    >
                      <TextArea
                        rows={7}
                        maxLength={2000}
                        value={question.prompt}
                        onChange={(event) => updateQuestion(question.clientId, event.target.value)}
                        placeholder="Write the question participants will answer…"
                      />
                    </Field>

                    <div className={styles.coverageEditor}>
                      <div className={styles.coverageHeading}>
                        <div>
                          <h3>What should every discussion cover?</h3>
                          <p>
                            Add the ideas, evidence, reasoning steps, or perspectives that should be represented in each group.
                          </p>
                        </div>
                        <span>{question.coverageUnits.length} of 8</span>
                      </div>
                      <div className={styles.coverageRows}>
                        {question.coverageUnits.map((unit, unitIndex) => (
                          <div className={styles.coverageRow} key={`${question.clientId}-unit-${unitIndex}`}>
                            <span aria-hidden="true">{unitIndex + 1}</span>
                            <Input
                              value={unit}
                              maxLength={240}
                              onChange={(event) =>
                                updateCoverageUnit(question.clientId, unitIndex, event.target.value)
                              }
                              placeholder="e.g. Explains the strongest objection to the position"
                              aria-label={`Coverage unit ${unitIndex + 1} for question ${index + 1}`}
                            />
                            <Button
                              type="button"
                              variant="quiet"
                              size="compact"
                              onClick={() => removeCoverageUnit(question.clientId, unitIndex)}
                              disabled={question.coverageUnits.length === 1}
                              aria-label={`Remove coverage unit ${unitIndex + 1}`}
                            >
                              Remove
                            </Button>
                          </div>
                        ))}
                      </div>
                      <Button
                        type="button"
                        variant="quiet"
                        size="compact"
                        leadingIcon={<Icon name="plus" size={16} />}
                        onClick={() => addCoverageUnit(question.clientId)}
                        disabled={question.coverageUnits.length >= 8}
                      >
                        Add coverage unit
                      </Button>
                    </div>
                  </article>
                ))}
              </div>

              <Button
                type="button"
                variant="secondary"
                leadingIcon={<Icon name="plus" size={17} />}
                onClick={() => updateDraft("questions", [...draft.questions, newQuestion()])}
                disabled={draft.questions.length >= 8}
              >
                Add another question
              </Button>
              {draft.questions.length >= 8 ? (
                <p className={styles.limitText}>An activity can contain up to 8 questions.</p>
              ) : null}
            </section>
          ) : null}

          {step === "review" ? (
            <section aria-labelledby="review-title">
              <header className={styles.sectionHeader}>
                <div>
                  <h1 id="review-title" ref={stepHeadingRef} tabIndex={-1}>Review and create</h1>
                  <p>Once created, Junto opens the invite lobby. The timer starts only when you start the activity.</p>
                </div>
              </header>

              <dl className={styles.reviewSummary}>
                <div>
                  <dt>Activity</dt>
                  <dd>{draft.title}</dd>
                </div>
                <div>
                  <dt>Response window</dt>
                  <dd>{formatDuration(draft.durationMinutes)}</dd>
                </div>
                <div>
                  <dt>Group size</dt>
                  <dd>About {draft.preferredGroupSize} people</dd>
                </div>
                <div>
                  <dt>Reference material</dt>
                  <dd>
                    {skipReference
                      ? "Skipped"
                      : draft.materialFile?.name ??
                        (draft.pastedReference.trim() ? "Pasted reference text" : "None")}
                  </dd>
                </div>
              </dl>

              <div className={styles.reviewQuestions}>
                <h2>{draft.questions.length} question{draft.questions.length === 1 ? "" : "s"}</h2>
                <ol>
                  {draft.questions.map((question) => (
                    <li key={question.clientId}>{question.prompt}</li>
                  ))}
                </ol>
              </div>

              <InlineNotice tone="info" title="What happens next">
                You’ll receive an invite code. Participants enter their names and wait in the lobby until you start the shared timer.
              </InlineNotice>
              {submitError ? (
                <InlineNotice
                  tone="error"
                  title={setupRoomId ? "Setup not finished" : "Activity not created"}
                >
                  <span>{submitError}</span>
                  {setupRoomId &&
                  (draft.materialFile || draft.pastedReference.trim()) &&
                  !skipReference ? (
                    <Button
                      className={styles.retryWithoutMaterial}
                      type="button"
                      variant="quiet"
                      size="compact"
                      onClick={() => {
                        setSkipReference(true);
                        setSubmitError(null);
                      }}
                    >
                      Continue without reference material
                    </Button>
                  ) : null}
                </InlineNotice>
              ) : null}
            </section>
          ) : null}

          <footer className={styles.formActions}>
            {activeIndex > 0 ? (
              <Button
                type="button"
                variant="secondary"
                onClick={previous}
                disabled={creating}
              >
                Back
              </Button>
            ) : (
              <Button type="button" variant="quiet" onClick={() => navigate("/")}>
                Cancel
              </Button>
            )}
            {step === "review" ? (
              <Button type="submit" loading={creating} loadingLabel="Creating activity">
                {setupRoomId ? "Retry setup" : "Create activity"}
              </Button>
            ) : (
              <Button
                key={`continue-${step}`}
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  next();
                }}
                disabled={!isStepValid(step)}
              >
                {step === "material" && !draft.materialFile && !draft.pastedReference.trim()
                  ? "Continue without material"
                  : "Continue"}
              </Button>
            )}
          </footer>
        </form>
      </div>
    </AppShell>
  );
}
