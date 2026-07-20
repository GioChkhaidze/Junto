import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell, ConnectionBanner, ContentStack } from "../../../components/layout";
import { Button, EmptyState, Icon, InlineNotice, LoadingSkeleton, TextArea } from "../../../components/ui";
import type { MyGroupResponse, ParticipantQuestion, ParticipantRoom, RoomStatusProjection } from "../../../domain";
import { useCountdown } from "../../../hooks/useCountdown";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { useOnlineStatus } from "../../../hooks/useOnlineStatus";
import { usePolling } from "../../../hooks/usePolling";
import { formatCountdown } from "../../../lib/format";
import { motionSafeScrollBehavior, scrollPageToTop } from "../../../lib/motion";
import styles from "./ParticipantRoomPage.module.css";

type SaveState = "idle" | "saving" | "saved" | "error";

const answerPlaceholder =
  "Write your response here. Explain your reasoning in enough detail for another person to follow it.";

function readableError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This room isn’t available in this browser. Rejoin with the invite code.";
  }
  if (error instanceof Error) return error.message;
  return "Junto couldn’t load the room.";
}

function analysisMessage(
  phase: ParticipantRoom["analysisPhase"],
  mode: ParticipantRoom["analysisMode"],
): { title: string; body: string } {
  if (phase === "complete") {
    return { title: "Results ready", body: "Junto is opening your discussion group now." };
  }
  if (mode === "coverage_aware" && phase === "forming_groups") {
    return {
      title: "Forming your discussion group",
      body: "Junto is building valid groups and preserving the strongest available coverage of each question.",
    };
  }
  if (mode === "coverage_aware") {
    return {
      title: "Interpreting the response set",
      body: "Junto is checking the submitted answers against the host-approved discussion coverage.",
    };
  }
  return {
    title: "Preparing groups",
    body: "Junto is balancing the room’s participant roster into discussion groups.",
  };
}

export function ParticipantRoomPage() {
  const { roomId = "" } = useParams<{ roomId: string }>();
  const online = useOnlineStatus();
  const [room, setRoom] = useState<ParticipantRoom | null>(null);
  const [group, setGroup] = useState<MyGroupResponse | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [savedAnswers, setSavedAnswers] = useState<Record<string, string>>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const saveInFlight = useRef(new Map<string, Promise<boolean>>());
  const answersRef = useRef<Record<string, string>>({});
  const savedAnswersRef = useRef<Record<string, string>>({});
  const questionHeadingRef = useRef<HTMLHeadingElement>(null);
  const reviewHeadingRef = useRef<HTMLHeadingElement>(null);
  const currentDotRef = useRef<HTMLButtonElement>(null);
  const remaining = useCountdown(room?.deadlineAt, room?.serverTime, room?.remainingSeconds);
  useDocumentTitle(room?.title ?? "Activity");

  const loadRoom = useCallback(async () => {
    try {
      const nextRoom = await api.getParticipantRoom(roomId);
      setRoom(nextRoom);
      setAnswers((current) => {
        const next = { ...current };
        for (const question of nextRoom.questions) {
          if (!(question.id in next)) next[question.id] = question.answer ?? "";
        }
        answersRef.current = next;
        return next;
      });
      setSavedAnswers((current) => {
        const next = { ...current };
        for (const question of nextRoom.questions) next[question.id] = question.answer ?? "";
        savedAnswersRef.current = next;
        return next;
      });
      setError(null);
      return nextRoom;
    } catch (reason) {
      setError(readableError(reason));
      return null;
    } finally {
      setLoading(false);
    }
  }, [roomId]);

  useEffect(() => {
    void loadRoom();
  }, [loadRoom]);

  const applyStatus = useCallback(
    async (status: RoomStatusProjection) => {
      setStatusError(null);
      const stateChanged = room?.status !== status.status;
      setRoom((current) => (current ? { ...current, ...status, questions: current.questions } : current));
      if (stateChanged && status.status === "answering") await loadRoom();
      if (status.status === "published" && !group) {
        try {
          setGroup(await api.getMyGroup(roomId));
        } catch (reason) {
          setStatusError(readableError(reason));
        }
      }
    },
    [group, loadRoom, room?.status, roomId],
  );

  usePolling(
    async () => {
      try {
        await applyStatus(await api.getRoomStatus(roomId));
      } catch (reason) {
        setStatusError(readableError(reason));
      }
    },
    {
      enabled: Boolean(room && room.status !== "published" && room.status !== "failed"),
      intervalMs: room?.status === "analyzing" ? 1400 : 2000,
    },
  );

  useEffect(() => {
    if (room?.status !== "published" || group) return;
    api
      .getMyGroup(roomId)
      .then(setGroup)
      .catch((reason: unknown) => setStatusError(readableError(reason)));
  }, [group, room?.status, roomId]);

  const questions = room?.questions ?? [];
  const onReviewPage = currentIndex >= questions.length;
  const currentQuestion = onReviewPage ? null : (questions[currentIndex] ?? null);
  const answeredCount = useMemo(
    () => questions.filter((question) => answers[question.id]?.trim()).length,
    [answers, questions],
  );

  useEffect(() => {
    if (room?.status !== "answering" || questions.length === 0) return;
    const heading = onReviewPage ? reviewHeadingRef.current : questionHeadingRef.current;
    heading?.focus({ preventScroll: true });
    scrollPageToTop();
    currentDotRef.current?.scrollIntoView?.({
      behavior: motionSafeScrollBehavior(),
      block: "nearest",
      inline: "center",
    });
  }, [currentIndex, onReviewPage, questions.length, room?.status]);

  const saveQuestion = useCallback(
    async (question: ParticipantQuestion | null): Promise<boolean> => {
      if (!question || !room || room.status !== "answering") return true;
      while (true) {
        const existingSave = saveInFlight.current.get(question.id);
        if (existingSave) {
          if (!(await existingSave)) return false;
          continue;
        }

        const value = answersRef.current[question.id] ?? "";
        if (value === (savedAnswersRef.current[question.id] ?? "")) return true;
        if (!online) {
          setSaveState("error");
          setError("Reconnect before moving on so Junto can save this answer.");
          return false;
        }

        let operation!: Promise<boolean>;
        operation = (async () => {
          setSaveState("saving");
          setError(null);
          try {
            await api.saveAnswer(roomId, question.id, { text: value });
            savedAnswersRef.current = { ...savedAnswersRef.current, [question.id]: value };
            setSavedAnswers(savedAnswersRef.current);
            setSaveState(answersRef.current[question.id] === value ? "saved" : "idle");
            return true;
          } catch (reason) {
            setSaveState("error");
            setError(readableError(reason));
            return false;
          } finally {
            if (saveInFlight.current.get(question.id) === operation) {
              saveInFlight.current.delete(question.id);
            }
          }
        })();
        saveInFlight.current.set(question.id, operation);
        if (!(await operation)) return false;
      }
    },
    [online, room, roomId],
  );

  useEffect(() => {
    if (
      room?.status !== "answering" ||
      room.submitted ||
      !currentQuestion ||
      remaining === 0 ||
      (answers[currentQuestion.id] ?? "") === (savedAnswers[currentQuestion.id] ?? "")
    ) {
      return;
    }
    const timeoutId = window.setTimeout(
      () => void saveQuestion(currentQuestion),
      remaining !== null && remaining <= 3 ? 0 : 900,
    );
    return () => window.clearTimeout(timeoutId);
  }, [answers, currentQuestion, remaining, room?.status, room?.submitted, saveQuestion, savedAnswers]);

  async function goTo(index: number) {
    if (index < 0 || index > questions.length) return;
    if (!(await saveQuestion(currentQuestion))) return;
    setCurrentIndex(index);
    setSaveState("saved");
  }

  async function submitAnswers() {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (!(await saveQuestion(currentQuestion))) return;
      const result = await api.submitResponses(roomId);
      setRoom((current) => (current ? { ...current, ...result, status: result.status, submitted: true } : current));
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <AppShell>
        <LoadingSkeleton count={7} />
      </AppShell>
    );
  }

  if (!room) {
    return (
      <AppShell>
        <ContentStack>
          <h1>Room unavailable</h1>
          <InlineNotice tone="error" title="Junto couldn’t load this room">
            {error ?? "Rejoin the activity using its invite code."}
          </InlineNotice>
        </ContentStack>
      </AppShell>
    );
  }

  if (room.status === "lobby") {
    return (
      <AppShell context={room.title}>
        <WaitingRoom title="You’re in the room" body="The host will start the activity when everyone has joined." />
        {statusError ? <p className={styles.pollingError}>{statusError}</p> : null}
      </AppShell>
    );
  }

  if (room.status === "published") {
    return (
      <AppShell context={room.title} wide>
        <ParticipantGroupView result={group} error={statusError} />
      </AppShell>
    );
  }

  if (room.status === "answering" && room.submitted) {
    return (
      <AppShell context={room.title}>
        <WaitingRoom
          title="Responses submitted"
          body="Your answers are locked. Group preparation begins when everyone submits or the shared timer expires."
        />
        <p className={styles.keepOpen}>Keep this page open. Your group will appear here automatically.</p>
        {statusError ? <p className={styles.pollingError}>{statusError}</p> : null}
      </AppShell>
    );
  }

  if (room.status === "analyzing") {
    const message = analysisMessage(room.analysisPhase, room.analysisMode);
    return (
      <AppShell context={room.title}>
        <WaitingRoom title={message.title} body={message.body} analyzing />
        <p className={styles.keepOpen}>Keep this page open. Your group will appear here automatically.</p>
        {statusError ? <p className={styles.pollingError}>{statusError}</p> : null}
      </AppShell>
    );
  }

  if (room.status === "failed") {
    return (
      <AppShell context={room.title}>
        <EmptyState
          icon={<Icon name="alert-circle" size={28} />}
          title="Group formation paused"
          description="The host has been notified. Keep this page open while they retry the activity."
          action={<Button onClick={() => void loadRoom()}>Check again</Button>}
        />
      </AppShell>
    );
  }

  if (room.status !== "answering" || questions.length === 0) {
    return (
      <AppShell context={room.title}>
        <WaitingRoom title="Waiting for questions" body="The host is preparing the activity." />
      </AppShell>
    );
  }

  return (
    <div className={styles.runnerShell}>
      <a className="skip-link" href="#question-content">
        Skip to question
      </a>
      <ConnectionBanner online={online} />
      <header className={styles.runnerHeader}>
        <div>
          <strong>Junto</strong>
          <span>{room.title}</span>
        </div>
        <div className={`${styles.timer} ${remaining !== null && remaining <= 60 ? styles.timerUrgent : ""}`}>
          <Icon name="clock" size={18} />
          <span>
            <span className="visually-hidden">Time remaining: </span>
            {remaining === null ? "In progress" : formatCountdown(remaining)}
          </span>
        </div>
      </header>

      <main id="question-content" className={styles.runnerMain}>
        {!onReviewPage && currentQuestion ? (
          <section className={styles.questionPage} aria-labelledby={`question-${currentQuestion.id}`}>
            <div className={styles.questionMeta}>
              <span>
                Question {currentIndex + 1} of {questions.length}
              </span>
              <SaveIndicator state={saveState} />
            </div>
            <h1 id={`question-${currentQuestion.id}`} ref={questionHeadingRef} tabIndex={-1}>
              {currentQuestion.prompt}
            </h1>
            <label className={styles.answerLabel} htmlFor={`answer-${currentQuestion.id}`}>
              Your response
            </label>
            <TextArea
              id={`answer-${currentQuestion.id}`}
              className={styles.answerArea}
              rows={12}
              maxLength={1500}
              value={answers[currentQuestion.id] ?? ""}
              onChange={(event) => {
                const value = event.target.value;
                setAnswers((current) => {
                  const next = { ...current, [currentQuestion.id]: value };
                  answersRef.current = next;
                  return next;
                });
                setSaveState("idle");
              }}
              onBlur={() => void saveQuestion(currentQuestion)}
              placeholder={answerPlaceholder}
              disabled={remaining === 0 || submitting}
              aria-describedby={`answer-help-${currentQuestion.id}`}
            />
            <div id={`answer-help-${currentQuestion.id}`} className={styles.answerHelp}>
              <span>Saved automatically and before you move between questions.</span>
              <span>{(answers[currentQuestion.id] ?? "").length.toLocaleString()} / 1,500</span>
            </div>
          </section>
        ) : (
          <section className={styles.reviewPage} aria-labelledby="submission-review-title">
            <p className={styles.reviewIntro}>Final step</p>
            <h1 id="submission-review-title" ref={reviewHeadingRef} tabIndex={-1}>
              Review your responses
            </h1>
            <p>
              You answered {answeredCount} of {questions.length} questions. You can return to any question before
              submitting.
            </p>
            <ol className={styles.answerReview}>
              {questions.map((question, index) => {
                const answered = Boolean(answers[question.id]?.trim());
                return (
                  <li key={question.id}>
                    <button type="button" onClick={() => void goTo(index)}>
                      <span className={answered ? styles.reviewAnswered : styles.reviewMissing}>
                        {answered ? <Icon name="check" size={16} /> : index + 1}
                      </span>
                      <span>
                        <strong>Question {index + 1}</strong>
                        <span>{question.prompt}</span>
                      </span>
                      <span className={styles.reviewState}>{answered ? "Answered" : "No response"}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
            <ContentStack spacing="compact">
              {error ? (
                <InlineNotice tone="error" title="Responses not submitted">
                  {error}
                </InlineNotice>
              ) : null}
              <Button
                fullWidth
                loading={submitting}
                loadingLabel="Submitting responses"
                onClick={() => void submitAnswers()}
                disabled={remaining === 0}
              >
                Submit responses
              </Button>
              <p className={styles.submitHelp}>After submitting, your answers can’t be changed.</p>
            </ContentStack>
          </section>
        )}

        {error && !onReviewPage ? (
          <InlineNotice className={styles.questionError} tone="error" title="Answer not saved">
            {error}
          </InlineNotice>
        ) : null}
      </main>

      <nav className={styles.runnerNavigation} aria-label="Question navigation">
        <Button
          className={styles.previousAction}
          variant="secondary"
          leadingIcon={<Icon name="arrow-left" size={18} />}
          onClick={() => void goTo(currentIndex - 1)}
          disabled={currentIndex === 0}
        >
          Previous
        </Button>
        <ol className={styles.questionDots}>
          {questions.map((question, index) => {
            const answered = Boolean(answers[question.id]?.trim());
            const current = index === currentIndex;
            return (
              <li key={question.id}>
                <button
                  ref={current ? currentDotRef : undefined}
                  type="button"
                  className={`${answered ? styles.dotAnswered : ""} ${current ? styles.dotCurrent : ""}`}
                  onClick={() => void goTo(index)}
                  aria-current={current ? "step" : undefined}
                  aria-label={`Question ${index + 1}, ${answered ? "answered" : "not answered"}`}
                >
                  {answered && !current ? <Icon name="check" size={17} /> : index + 1}
                </button>
              </li>
            );
          })}
        </ol>
        <Button
          className={styles.nextAction}
          onClick={() => void goTo(currentIndex + 1)}
          disabled={currentIndex >= questions.length}
          trailingIcon={<Icon name="arrow-right" size={18} />}
        >
          {currentIndex === questions.length - 1 ? "Review responses" : "Next question"}
        </Button>
        <span className={`${styles.progressText} visually-hidden`}>{answeredCount} answered</span>
      </nav>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state === "saving")
    return (
      <span className={styles.saveIndicator} role="status" aria-live="polite">
        Saving…
      </span>
    );
  if (state === "error")
    return (
      <span className={styles.saveError} role="status" aria-live="polite">
        Not saved
      </span>
    );
  if (state === "saved") {
    return (
      <span className={styles.saveIndicator} role="status" aria-live="polite">
        <Icon name="check" size={15} /> Saved
      </span>
    );
  }
  return (
    <span className={styles.saveIndicator} role="status" aria-live="polite">
      Editing
    </span>
  );
}

function WaitingRoom({ title, body, analyzing = false }: { title: string; body: string; analyzing?: boolean }) {
  return (
    <div className={styles.waitingRoom}>
      <p className={styles.waitingStatus}>{analyzing ? "Group preparation" : "Waiting for host"}</p>
      <h1>{title}</h1>
      <p>{body}</p>
      {analyzing ? (
        <div className={styles.waitingLine} aria-hidden="true">
          <span />
        </div>
      ) : null}
    </div>
  );
}

function ParticipantGroupView({ result, error }: { result: MyGroupResponse | null; error: string | null }) {
  if (!result) {
    return (
      <ContentStack>
        <LoadingSkeleton count={6} />
        {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
      </ContentStack>
    );
  }

  if (result.generationMode === "coverage_aware") {
    return (
      <div className={styles.groupPage}>
        <header className={styles.groupHeader}>
          <div>
            <p>Your discussion group</p>
            <h1>Meet your group</h1>
            <span>Work through the agenda in order. The names beside each idea show who can help introduce it.</span>
          </div>
          <div className={styles.groupNumber}>Group {result.group.id.replace(/^g/i, "") || result.group.id}</div>
        </header>

        <section className={styles.membersSection} aria-labelledby="members-title">
          <h2 id="members-title">Group members</h2>
          <ul>
            {result.group.members.map((member) => (
              <li key={member.participantId}>
                <strong>{member.displayName}</strong>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.agenda} aria-labelledby="agenda-title">
          <div className={styles.agendaHeading}>
            <h2 id="agenda-title">Discussion agenda</h2>
            <p>Coverage describes what appeared in submitted answers; it is not a grade.</p>
          </div>
          {result.group.questions.map((question) => (
            <section key={question.questionId} aria-labelledby={`agenda-${question.questionId}`}>
              <div className={styles.agendaQuestionHeading}>
                <span>Question {question.position + 1}</span>
                <h3 id={`agenda-${question.questionId}`}>{question.prompt}</h3>
              </div>
              <ol className={styles.agendaUnits}>
                {question.units.map((unit) => (
                  <li key={unit.id} data-covered={unit.covered}>
                    <span aria-hidden="true">{unit.covered ? "✓" : "—"}</span>
                    <div>
                      <strong>{unit.text}</strong>
                      <p>
                        {unit.carriers.length
                          ? `Ask ${unit.carriers.map((carrier) => carrier.displayName).join(" or ")} ` +
                            "to introduce this idea."
                          : "No submitted answer clearly covered this idea. Work it out together."}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
              {question.representedFamilies.length > 1 ? (
                <div className={styles.agendaFamilies}>
                  <h4>Approaches to compare</h4>
                  <dl>
                    {question.representedFamilies.map((family) => (
                      <div key={family.id}>
                        <dt>{family.label}</dt>
                        <dd>{family.members.map((member) => member.displayName).join(", ")}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ) : null}
            </section>
          ))}
        </section>
      </div>
    );
  }

  return (
    <div className={styles.groupPage}>
      <header className={styles.groupHeader}>
        <div>
          <p>Your discussion group</p>
          <h1>Meet your group</h1>
          <span>Bring your response into the conversation and compare how each person approached the questions.</span>
        </div>
        <div className={styles.groupNumber}>Group {result.group.id.replace(/^g/i, "") || result.group.id}</div>
      </header>

      <section className={styles.membersSection} aria-labelledby="members-title">
        <h2 id="members-title">Group members</h2>
        <ul>
          {result.group.members.map((member) => (
            <li key={member.participantId}>
              <strong>{member.displayName}</strong>
            </li>
          ))}
        </ul>
      </section>

      <InlineNotice tone="info" title="Start the discussion">
        Introduce yourselves, then take each question in order. Ask what evidence or reasoning led each person to their
        answer.
      </InlineNotice>
    </div>
  );
}
