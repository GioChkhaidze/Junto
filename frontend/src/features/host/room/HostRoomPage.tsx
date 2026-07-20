import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell, ContentActions, ContentStack } from "../../../components/layout";
import { Button, EmptyState, Icon, InlineNotice, LoadingSkeleton } from "../../../components/ui";
import type {
  HostGroupsResponse,
  HostRoom,
  SyntheticClassroomProjection,
  SyntheticResponseSource,
} from "../../../domain";
import { useCountdown } from "../../../hooks/useCountdown";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { usePolling } from "../../../hooks/usePolling";
import { copyText, formatCountdown, formatDuration } from "../../../lib/format";
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
const feasibleSolverMessage =
  "This is the best valid partition found within the configured solve limit; optimality was not proved for " +
  "every objective.";
const fallbackSolverMessage =
  "The semantic optimizer returned no partition in time, so Junto published its deterministic capacity-valid fallback.";

function readableError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This room isn’t available in this browser.";
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
    enabled: Boolean(room && room.status !== "published" && room.status !== "failed"),
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
    try {
      await action();
      setSetupWarning(null);
      await loadRoom();
    } catch (reason) {
      setError(readableError(reason));
    } finally {
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
            onGenerateSynthetic={(source) =>
              run(async () => {
                const result = await api.generateSyntheticResponses(roomId, { source });
                setSyntheticClassroom(result.simulation);
              })
            }
          />
        ) : null}

        {room.status === "analyzing" ? <AnalysisView mode={room.analysisMode} phase={room.analysisPhase} /> : null}

        {room.status === "published" ? <AllGroupsView room={room} result={groups} /> : null}

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
  const canStart = room.startEligibility.eligible && room.allowedActions.includes("startActivity");
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
          <p>{room.startEligibility.message}</p>
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
  onGenerateSynthetic: (source: SyntheticResponseSource) => Promise<void>;
}) {
  const [confirmEnd, setConfirmEnd] = useState(false);
  const total = room.progress.possibleResponseCount;
  const answered = room.progress.answeredResponseCount;
  const percent = total > 0 ? Math.round((answered / total) * 100) : 0;
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
                  Participants will be unable to make further changes. Junto will use every answer saved so far and
                  begin preparing groups immediately.
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
              <Button variant="secondary" onClick={() => setConfirmEnd(true)}>
                End responses early
              </Button>
            </>
          )}
        </section>
      ) : null}

      <ParticipantRoster room={room} />
    </div>
  );
}

function ParticipantRoster({
  room,
  canRemove = false,
  onRemove,
}: {
  room: HostRoom;
  canRemove?: boolean;
  onRemove?: (participantId: string) => void;
}) {
  return (
    <section className={styles.roster} aria-labelledby="roster-title">
      <div className={styles.sectionTitleRow}>
        <h2 id="roster-title">Participants</h2>
        <span>{room.participants.length} joined</span>
      </div>
      {room.participants.length ? (
        <ul>
          {room.participants.map((participant, index) => (
            <li key={participant.participantId}>
              <span className={styles.rosterNumber}>{index + 1}</span>
              <strong>{participant.displayName}</strong>
              <span className={participant.submittedAt ? styles.submitted : styles.waiting}>
                {participant.submittedAt ? "Submitted" : room.status === "answering" ? "Working" : "Waiting"}
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
          ))}
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

function AllGroupsView({ room, result }: { room: HostRoom; result: HostGroupsResponse | null }) {
  if (!result) return <LoadingSkeleton count={7} label="Loading group rosters" />;
  if (result.generationMode === "placeholder") {
    return (
      <div className={styles.groupsView}>
        <header className={styles.pageHeader}>
          <div>
            <p>Room results</p>
            <h1>Discussion groups</h1>
            <span>
              {result.groups.length} {result.groups.length === 1 ? "group" : "groups"} formed from{" "}
              {room.progress.participantCount} {room.progress.participantCount === 1 ? "participant" : "participants"}.
            </span>
          </div>
        </header>

        <ContentStack>
          <InlineNotice tone="info" title="Capacity grouping">
            This room used stable roster order and valid group sizes. Responses were not interpreted.
          </InlineNotice>
          <div className={styles.groupList}>
            {result.groups.map((group, index) => (
              <section key={group.id} aria-labelledby={`group-${group.id}`}>
                <div className={styles.groupTitleRow}>
                  <h2 id={`group-${group.id}`}>Group {index + 1}</h2>
                  <span>{group.members.length} members</span>
                </div>
                <ol>
                  {group.members.map((member) => (
                    <li key={member.participantId}>{member.displayName}</li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
        </ContentStack>
      </div>
    );
  }

  const complete = result.coverageReport.fullyCoveredGroupQuestions;
  const total = result.coverageReport.totalGroupQuestions;
  const solverMessage =
    result.solver.status === "optimal"
      ? "The solver proved every listed objective before moving to the next priority."
      : result.solver.status === "feasible"
        ? feasibleSolverMessage
        : fallbackSolverMessage;
  const feasibilityMessage =
    result.solver.completeCoverageStatus === "feasible"
      ? "A complete-coverage partition was found."
      : result.solver.completeCoverageStatus === "infeasible"
        ? "The solver proved that complete coverage is impossible for this cohort and these group sizes."
        : "Complete-coverage feasibility was not resolved within the solve limit.";

  return (
    <div className={styles.groupsView}>
      <header className={styles.pageHeader}>
        <div>
          <p>Room results</p>
          <h1>Coverage-aware groups</h1>
          <span>
            {complete} of {total} group-question discussions include every approved coverage unit.
          </span>
        </div>
      </header>

      <section className={styles.resultSummary} aria-labelledby="result-summary-title">
        <h2 id="result-summary-title">What this result guarantees</h2>
        <p>
          {feasibilityMessage} {solverMessage}
        </p>
        <dl>
          <div>
            <dt>Coverage achieved</dt>
            <dd>
              {complete} / {total}
            </dd>
          </div>
          <div>
            <dt>Groups</dt>
            <dd>{result.groups.length}</dd>
          </div>
          <div>
            <dt>Grouping policy</dt>
            <dd>{result.policy === "teach" ? "Teach each other" : "Explore approaches"}</dd>
          </div>
        </dl>
      </section>

      <div className={styles.coverageGroupList}>
        {result.groups.map((group, index) => (
          <section className={styles.coverageGroup} key={group.id} aria-labelledby={`group-${group.id}`}>
            <div className={styles.groupTitleRow}>
              <h2 id={`group-${group.id}`}>Group {index + 1}</h2>
              <span>{group.members.length} members</span>
            </div>
            <ul className={styles.groupMembers} aria-label={`Group ${index + 1} members`}>
              {group.members.map((member) => (
                <li key={member.participantId}>{member.displayName}</li>
              ))}
            </ul>
            <div className={styles.questionResults}>
              {group.questions.map((question) => {
                const unitById = new Map(question.units.map((unit) => [unit.id, unit.text]));
                return (
                  <section key={question.questionId} aria-labelledby={`${group.id}-${question.questionId}`}>
                    <div className={styles.questionResultHeading}>
                      <div>
                        <span>Question {question.position + 1}</span>
                        <h3 id={`${group.id}-${question.questionId}`}>{question.prompt}</h3>
                      </div>
                      <strong>{question.fullyCovered ? "Complete coverage" : "Coverage gap"}</strong>
                    </div>
                    <ul className={styles.coverageRows}>
                      {question.units.map((unit) => (
                        <li key={unit.id} data-covered={unit.covered}>
                          <span aria-hidden="true">{unit.covered ? "✓" : "—"}</span>
                          <div>
                            <strong>{unit.text}</strong>
                            <span>
                              {unit.carriers.length
                                ? `Supported by ${unit.carriers.map((carrier) => carrier.displayName).join(", ")}`
                                : "No submitted answer clearly supported this unit"}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                    {question.representedFamilies.length ? (
                      <div className={styles.familySummary}>
                        <h4>Approaches represented</h4>
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
                    <details className={styles.responseAudit}>
                      <summary>Review answer classifications</summary>
                      <div>
                        {(question.responseAudit ?? []).map((response) => (
                          <article key={response.participant.participantId}>
                            <header>
                              <strong>{response.participant.displayName}</strong>
                              <span>{response.family?.label ?? "No clear approach family"}</span>
                            </header>
                            <p>
                              {response.coveredUnitIds.length
                                ? `Coverage: ${response.coveredUnitIds.map((id) => unitById.get(id) ?? id).join("; ")}`
                                : "No approved coverage unit was supported."}
                            </p>
                            <blockquote>{response.answer ?? "No answer submitted."}</blockquote>
                          </article>
                        ))}
                      </div>
                    </details>
                  </section>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
