import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell, ContentActions, ContentStack, HeaderLink } from "../../../components/layout";
import { Button, EmptyState, Icon, InlineNotice, LoadingSkeleton } from "../../../components/ui";
import type {
  GenerateSyntheticResponsesResponse,
  HostGroupsResponse,
  HostRoom,
  SyntheticClassroomProjection,
} from "../../../domain";
import { useCountdown } from "../../../hooks/useCountdown";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { usePolling } from "../../../hooks/usePolling";
import { copyText, formatCountdown, formatDuration } from "../../../lib/format";
import { HostResults } from "../results/HostResults";
import { SyntheticClassroomSection } from "../simulation/SyntheticClassroomSection";
import styles from "./HostRoomPage.module.css";

interface HostLocationState {
  newlyCreated?: boolean;
  setupError?: string;
}

const optimizerAnalysisBody =
  "The optimizer is assigning every participant once, respecting group sizes, and preserving the strongest " +
  "coverage it can prove.";
const interpretationAnalysisBody =
  "Junto is checking each answer against the approved coverage units and identifying approaches in a separate pass.";
function readableError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This room isn’t available in this browser.";
  }
  if (error instanceof Error && error.name === "TimeoutError") {
    return "Simulated response generation timed out. Check the OpenRouter connection and try again.";
  }
  if (error instanceof Error) return error.message;
  return "Junto couldn’t load the room.";
}

export function HostRoomPage() {
  const { roomId = "" } = useParams<{ roomId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = (location.state ?? {}) as HostLocationState;
  const [room, setRoom] = useState<HostRoom | null>(null);
  const [groups, setGroups] = useState<HostGroupsResponse | null>(null);
  const [syntheticClassroom, setSyntheticClassroom] = useState<SyntheticClassroomProjection | null>(null);
  const [syntheticGeneration, setSyntheticGeneration] = useState<GenerateSyntheticResponsesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupWarning, setSetupWarning] = useState<string | null>(locationState.setupError ?? null);
  const [copied, setCopied] = useState<"code" | "link" | null>(null);
  const remaining = useCountdown(room?.deadlineAt, room?.serverTime, room?.remainingSeconds);
  useDocumentTitle(room?.title ?? "Host room");

  const loadRoom = useCallback(async () => {
    try {
      const next = await api.getRoom(roomId);
      setRoom(next);
      setError(null);
      if (next.status === "lobby" || next.status === "answering") {
        try {
          setSyntheticClassroom(await api.getSyntheticClassroom(roomId));
        } catch (reason) {
          setSyntheticClassroom(null);
          if (!(reason instanceof ApiError && reason.status === 404)) {
            setError(readableError(reason));
          }
        }
      } else {
        setSyntheticClassroom(null);
      }
      if (next.status === "published") {
        try {
          setGroups(await api.getGroups(roomId));
        } catch (reason) {
          setError(readableError(reason));
        }
      }
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setLoading(false);
    }
  }, [roomId]);

  useEffect(() => {
    void loadRoom();
  }, [loadRoom]);

  usePolling(loadRoom, {
    enabled: Boolean(room && room.status !== "failed" && (room.status !== "published" || groups === null)),
    intervalMs: room?.status === "analyzing" ? 1400 : 2000,
  });

  const inviteUrl = useMemo(() => {
    if (!room?.joinCode) return "";
    return `${window.location.origin}/join/${room.joinCode}`;
  }, [room?.joinCode]);

  async function copy(value: string, type: "code" | "link") {
    try {
      await copyText(value);
      setCopied(type);
      window.setTimeout(() => setCopied(null), 1800);
    } catch {
      setError("Copying was blocked by this browser. Select the value and copy it manually.");
    }
  }

  async function run(action: () => Promise<unknown>) {
    setWorking(true);
    setError(null);
    let actionError: string | null = null;
    try {
      await action();
      setSetupWarning(null);
    } catch (reason) {
      actionError = readableError(reason);
    } finally {
      await loadRoom();
      if (actionError) setError(actionError);
      setWorking(false);
    }
  }

  if (loading) {
    return (
      <AppShell variant="host">
        <div className={styles.roomColumn}>
          <LoadingSkeleton count={8} />
        </div>
      </AppShell>
    );
  }

  if (!room) {
    return (
      <AppShell variant="host">
        <ContentStack className={styles.roomColumn}>
          <h1>Room unavailable</h1>
          <InlineNotice tone="error" title="Junto couldn’t open this room">
            {error ?? "The host link may be incomplete or no longer available."}
          </InlineNotice>
          <ContentActions>
            <Button variant="secondary" onClick={() => navigate("/")}>
              Return home
            </Button>
          </ContentActions>
        </ContentStack>
      </AppShell>
    );
  }

  return (
    <AppShell
      context={room.title}
      variant="host"
      actions={
        <>
          <HeaderLink to="/activities">Activities</HeaderLink>
          <RoomState status={room.status}>
            {room.status === "answering" && remaining !== null
              ? `${formatCountdown(remaining)} remaining`
              : room.status === "lobby"
                ? "Invite lobby"
                : room.status === "published"
                  ? "Groups ready"
                  : room.status === "analyzing"
                    ? "Preparing groups"
                    : "Draft"}
          </RoomState>
        </>
      }
    >
      <ContentStack>
        {error ? (
          <InlineNotice tone="error" title="Action needed">
            {error}
          </InlineNotice>
        ) : null}
        {setupWarning ? (
          <InlineNotice tone="warning" title="Draft needs review">
            {setupWarning}
          </InlineNotice>
        ) : null}
        {syntheticGeneration ? (
          <InlineNotice tone="success" title="Simulated responses submitted" role="status">
            {syntheticGeneration.participantCount} simulated participants submitted {syntheticGeneration.responseCount}
            {" question responses through "}
            {syntheticGeneration.source === "openrouter" ? "OpenRouter" : "the local fixture generator"}.
            {syntheticGeneration.models.length
              ? ` Models: ${syntheticGeneration.models.join(", ")}.`
              : " The provider did not report a model."}
          </InlineNotice>
        ) : null}

        {room.status === "draft" ? (
          <DraftRoom room={room} working={working} onOpen={() => void run(() => api.openRoom(roomId))} />
        ) : null}

        {room.status === "lobby" ? (
          <Lobby
            room={room}
            inviteUrl={inviteUrl}
            copied={copied}
            working={working}
            onCopy={copy}
            onStart={() => void run(() => api.startActivity(roomId))}
            onRemove={(participantId) => void run(() => api.removeParticipant(roomId, participantId))}
            syntheticClassroom={syntheticClassroom}
            onConfigureSynthetic={(targetSize) =>
              run(async () => {
                setSyntheticClassroom(await api.configureSyntheticCohort(roomId, { targetSize }));
              })
            }
          />
        ) : null}

        {room.status === "answering" ? (
          <CollectionView
            room={room}
            remaining={remaining}
            working={working}
            onEnd={() => void run(() => api.startAnalysis(roomId))}
            syntheticClassroom={syntheticClassroom}
            onGenerateSynthetic={() =>
              run(async () => {
                setSyntheticGeneration(null);
                const result = await api.generateSyntheticResponses(roomId, { source: "openrouter" });
                setSyntheticClassroom(result.simulation);
                setSyntheticGeneration(result);
              })
            }
          />
        ) : null}

        {room.status === "analyzing" ? <AnalysisView mode={room.analysisMode} phase={room.analysisPhase} /> : null}

        {room.status === "published" ? <HostResults room={room} result={groups} /> : null}

        {room.status === "failed" ? (
          <div className={styles.roomColumn}>
            <EmptyState
              icon={<Icon name="alert-circle" size={28} />}
              title="Group formation stopped"
              description={
                room.lastError ?? "Junto couldn’t complete this run. The room’s submitted answers are unchanged."
              }
              action={
                room.allowedActions.includes("retryAnalysis") ? (
                  <Button loading={working} onClick={() => void run(() => api.retryAnalysis(roomId))}>
                    Retry group formation
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => void loadRoom()}>
                    Check status
                  </Button>
                )
              }
            />
          </div>
        ) : null}
      </ContentStack>
    </AppShell>
  );
}

function RoomState({ children, status }: { children: string; status: HostRoom["status"] }) {
  const announcement: Record<HostRoom["status"], string> = {
    draft: "Draft room",
    lobby: "Invite lobby open",
    answering: "Responses are open",
    analyzing: "Preparing groups",
    published: "Groups ready",
    failed: "Group formation failed",
  };

  return (
    <>
      <span className={styles.roomState} data-state={status}>
        <span aria-hidden="true" />
        {children}
      </span>
      <span className="visually-hidden" role="status">
        {announcement[status]}
      </span>
    </>
  );
}

function DraftRoom({ room, working, onOpen }: { room: HostRoom; working: boolean; onOpen: () => void }) {
  return (
    <div className={styles.roomColumn}>
      <header className={styles.pageHeader}>
        <div>
          <p>Draft activity</p>
          <h1>{room.title}</h1>
          <span>Review the saved setup, then open the invitation lobby.</span>
        </div>
        <Button loading={working} onClick={onOpen} disabled={room.questions.length === 0}>
          Open invite lobby
        </Button>
      </header>
      <dl className={styles.definitionList} aria-label="Activity setup">
        <div>
          <dt>Questions</dt>
          <dd>{room.questions.length}</dd>
        </div>
        <div>
          <dt>Response time</dt>
          <dd>{formatDuration(room.durationMinutes)}</dd>
        </div>
        <div>
          <dt>Reference files</dt>
          <dd>{room.materials.length}</dd>
        </div>
      </dl>
      <section className={styles.questionPreview}>
        <h2>Questions</h2>
        <ol>
          {room.questions.map((question) => (
            <li key={question.id}>{question.prompt}</li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function Lobby({
  room,
  inviteUrl,
  copied,
  working,
  onCopy,
  onStart,
  onRemove,
  syntheticClassroom,
  onConfigureSynthetic,
}: {
  room: HostRoom;
  inviteUrl: string;
  copied: "code" | "link" | null;
  working: boolean;
  onCopy: (value: string, type: "code" | "link") => void;
  onStart: () => void;
  onRemove: (participantId: string) => void;
  syntheticClassroom: SyntheticClassroomProjection | null;
  onConfigureSynthetic: (targetSize: number) => Promise<void>;
}) {
  const syntheticRosterBlocked = Boolean(
    syntheticClassroom?.syntheticParticipantCount && !syntheticClassroom.openRouterAvailable,
  );
  const canStart =
    room.startEligibility.eligible && room.allowedActions.includes("startActivity") && !syntheticRosterBlocked;
  const startMessage = syntheticRosterBlocked
    ? "Remove the simulated roster or configure OpenRouter before starting."
    : room.startEligibility.message;
  return (
    <div className={styles.roomColumn}>
      <header className={styles.pageHeader}>
        <div>
          <p>Invite participants</p>
          <h1>{room.title}</h1>
          <span>The timer has not started. Participants wait after entering their names.</span>
        </div>
      </header>

      <div className={styles.lobbyGrid}>
        <section className={styles.inviteSection} aria-labelledby="invite-title">
          <h2 id="invite-title">Share the room</h2>
          <p>Ask participants to visit Junto and enter this code.</p>
          <div className={styles.inviteCodeRow}>
            <code>{room.joinCode}</code>
            <Button
              variant="secondary"
              size="compact"
              leadingIcon={<Icon name={copied === "code" ? "check" : "copy"} size={16} />}
              onClick={() => room.joinCode && onCopy(room.joinCode, "code")}
            >
              {copied === "code" ? "Copied" : "Copy code"}
            </Button>
          </div>
          <div className={styles.inviteLinkRow}>
            <span>{inviteUrl}</span>
            <Button
              variant="quiet"
              size="compact"
              leadingIcon={<Icon name={copied === "link" ? "check" : "copy"} size={16} />}
              onClick={() => onCopy(inviteUrl, "link")}
            >
              {copied === "link" ? "Copied" : "Copy link"}
            </Button>
          </div>
        </section>

        <section className={styles.startSection} aria-labelledby="start-title">
          <h2 id="start-title">Start when the room is ready</h2>
          <dl>
            <div>
              <dt>Joined</dt>
              <dd>{room.progress.participantCount}</dd>
            </div>
            <div>
              <dt>Response window</dt>
              <dd>{formatDuration(room.durationMinutes)}</dd>
            </div>
            <div>
              <dt>Questions</dt>
              <dd>{room.questions.length}</dd>
            </div>
          </dl>
          <Button fullWidth loading={working} onClick={onStart} disabled={!canStart}>
            Start activity
          </Button>
          <p>{startMessage}</p>
        </section>
      </div>

      {syntheticClassroom ? (
        <SyntheticClassroomSection
          projection={syntheticClassroom}
          working={working}
          onConfigure={onConfigureSynthetic}
        />
      ) : null}

      <ParticipantRoster room={room} canRemove onRemove={onRemove} />
    </div>
  );
}

function CollectionView({
  room,
  remaining,
  working,
  onEnd,
  syntheticClassroom,
  onGenerateSynthetic,
}: {
  room: HostRoom;
  remaining: number | null;
  working: boolean;
  onEnd: () => void;
  syntheticClassroom: SyntheticClassroomProjection | null;
  onGenerateSynthetic: () => Promise<void>;
}) {
  const [confirmEnd, setConfirmEnd] = useState(false);
  const total = room.progress.possibleResponseCount;
  const answered = room.progress.answeredResponseCount;
  const percent = total > 0 ? Math.round((answered / total) * 100) : 0;
  const simulationRunning = syntheticClassroom?.generation?.status === "running";
  const pendingSimulated = syntheticClassroom?.pendingSyntheticParticipantCount ?? 0;
  return (
    <div className={styles.roomColumn}>
      <header className={styles.pageHeader}>
        <div>
          <p>Responses open</p>
          <h1>{room.title}</h1>
          <span>Group formation starts automatically when everyone submits or time expires.</span>
        </div>
        <div className={styles.largeTimer}>
          <Icon name="clock" size={20} />
          <strong>{remaining === null ? "In progress" : formatCountdown(remaining)}</strong>
          <span>remaining</span>
        </div>
      </header>

      <section className={styles.responseProgress} aria-labelledby="response-progress-title">
        <div>
          <h2 id="response-progress-title">Response progress</h2>
          <span>
            {answered} of {total} question responses saved
          </span>
        </div>
        <strong>{percent}%</strong>
        <div className={styles.progressTrack} aria-hidden="true">
          <span style={{ width: `${percent}%` }} />
        </div>
      </section>

      {syntheticClassroom ? (
        <SyntheticClassroomSection projection={syntheticClassroom} working={working} onGenerate={onGenerateSynthetic} />
      ) : null}

      {room.allowedActions.includes("startAnalysis") ? (
        <section className={styles.endResponses} aria-labelledby="end-responses-title">
          {confirmEnd ? (
            <>
              <div>
                <h2 id="end-responses-title">End responses now?</h2>
                <p>
                  Participants will be unable to make further changes. Junto will use every answer saved so far
                  {pendingSimulated ? `; ${pendingSimulated} simulated students will remain unanswered` : ""} and begin
                  preparing groups immediately.
                </p>
              </div>
              <div className={styles.endResponseActions}>
                <Button variant="secondary" onClick={() => setConfirmEnd(false)} disabled={working}>
                  Keep responses open
                </Button>
                <Button variant="danger" onClick={onEnd} loading={working} loadingLabel="Ending responses">
                  End responses and prepare groups
                </Button>
              </div>
            </>
          ) : (
            <>
              <div>
                <h2 id="end-responses-title">Need to finish early?</h2>
                <p>Close the response window before the timer ends and use all answers saved so far.</p>
              </div>
              <Button variant="secondary" onClick={() => setConfirmEnd(true)} disabled={working || simulationRunning}>
                End responses early
              </Button>
            </>
          )}
        </section>
      ) : null}

      <ParticipantRoster room={room} syntheticClassroom={syntheticClassroom} />
    </div>
  );
}

function ParticipantRoster({
  room,
  canRemove = false,
  onRemove,
  syntheticClassroom,
}: {
  room: HostRoom;
  canRemove?: boolean;
  onRemove?: (participantId: string) => void;
  syntheticClassroom?: SyntheticClassroomProjection | null;
}) {
  const pendingSyntheticIds = new Set(syntheticClassroom?.pendingSyntheticParticipantIds ?? []);
  const generationStatus = syntheticClassroom?.generation?.status;
  return (
    <section className={styles.roster} aria-labelledby="roster-title">
      <div className={styles.sectionTitleRow}>
        <h2 id="roster-title">Participants</h2>
        <span>{room.participants.length} joined</span>
      </div>
      {room.participants.length ? (
        <ul>
          {room.participants.map((participant, index) => {
            const pendingSynthetic = pendingSyntheticIds.has(participant.participantId);
            const state = participant.submittedAt
              ? "submitted"
              : pendingSynthetic && generationStatus === "running"
                ? "generating"
                : pendingSynthetic && generationStatus === "failed"
                  ? "retry"
                  : room.status === "answering"
                    ? "working"
                    : "waiting";
            const stateLabel = {
              submitted: "Submitted",
              generating: "Generating",
              retry: "Needs retry",
              working: "Working",
              waiting: "Waiting",
            }[state];
            return (
              <li key={participant.participantId}>
                <span className={styles.rosterNumber}>{index + 1}</span>
                <strong>{participant.displayName}</strong>
                <span className={state === "submitted" ? styles.submitted : styles.waiting} data-state={state}>
                  {stateLabel}
                </span>
                {canRemove && onRemove ? (
                  <Button
                    variant="quiet"
                    size="compact"
                    onClick={() => onRemove(participant.participantId)}
                    aria-label={`Remove ${participant.displayName} from the room`}
                  >
                    Remove
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <div className={styles.rosterEmpty}>
          <p>No one has joined yet. Keep this page open while participants use the invite code.</p>
        </div>
      )}
    </section>
  );
}

function AnalysisView({ mode, phase }: { mode: HostRoom["analysisMode"]; phase: HostRoom["analysisPhase"] }) {
  const coverageCopy =
    phase === "forming_groups"
      ? {
          title: "Forming coverage-aware groups",
          body: optimizerAnalysisBody,
          note: "Coverage is fixed before the selected Teach or Explore policy is used as a tie-breaker.",
        }
      : {
          title: "Interpreting the response set",
          body: interpretationAnalysisBody,
          note: "An approach never grants coverage that an individual answer did not support.",
        };
  const copy =
    mode === "coverage_aware"
      ? coverageCopy
      : {
          title: "Preparing groups",
          body: "Junto is balancing the frozen participant roster into valid group sizes.",
          note: "This room uses deterministic capacity grouping and does not interpret response meaning.",
        };
  return (
    <div className={styles.analysisView}>
      <p>Group preparation</p>
      <h1>{copy.title}</h1>
      <span>{copy.body}</span>
      <div className={styles.analysisRule} aria-hidden="true">
        <span />
      </div>
      <p className={styles.analysisNote}>{copy.note}</p>
    </div>
  );
}
