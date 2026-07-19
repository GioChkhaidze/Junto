import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell } from "../../../components/layout";
import {
  Button,
  EmptyState,
  Icon,
  InlineNotice,
  LoadingSkeleton,
} from "../../../components/ui";
import type { HostGroupsResponse, HostRoom } from "../../../domain";
import { useCountdown } from "../../../hooks/useCountdown";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { usePolling } from "../../../hooks/usePolling";
import { copyText, formatCountdown, formatDuration } from "../../../lib/format";
import styles from "./HostRoomPage.module.css";

interface HostLocationState {
  newlyCreated?: boolean;
  setupError?: string;
}

function readableError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This room isn’t available in this browser.";
  }
  if (error instanceof Error) return error.message;
  return "Junto couldn’t load the room.";
}

function hasFeasibleGroupCount(participantCount: number, minimum: number, maximum: number): boolean {
  if (participantCount < minimum) return false;
  for (let groups = 1; groups <= participantCount; groups += 1) {
    if (groups * minimum <= participantCount && participantCount <= groups * maximum) return true;
  }
  return false;
}

export function HostRoomPage() {
  const { roomId = "" } = useParams<{ roomId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = (location.state ?? {}) as HostLocationState;
  const [room, setRoom] = useState<HostRoom | null>(null);
  const [groups, setGroups] = useState<HostGroupsResponse | null>(null);
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
      <AppShell wide>
        <LoadingSkeleton count={8} />
      </AppShell>
    );
  }

  if (!room) {
    return (
      <AppShell>
        <h1>Room unavailable</h1>
        <InlineNotice tone="error" title="Junto couldn’t open this room">
          {error ?? "The host link may be incomplete or no longer available."}
        </InlineNotice>
        <Button variant="secondary" onClick={() => navigate("/")}>
          Return home
        </Button>
      </AppShell>
    );
  }

  return (
    <AppShell
      context={room.title}
      wide
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
        />
      ) : null}

      {room.status === "answering" ? (
        <CollectionView
          room={room}
          remaining={remaining}
          working={working}
          onEnd={() => void run(() => api.startAnalysis(roomId))}
        />
      ) : null}

      {room.status === "analyzing" ? <AnalysisView /> : null}

      {room.status === "published" ? <AllGroupsView room={room} result={groups} /> : null}

      {room.status === "failed" ? (
        <EmptyState
          icon={<Icon name="alert-circle" size={28} />}
          title="Group formation stopped"
          description={room.lastError ?? "Junto couldn’t complete this run. The room’s submitted answers are unchanged."}
          action={<Button variant="secondary" onClick={() => void loadRoom()}>Check status</Button>}
        />
      ) : null}
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

function DraftRoom({
  room,
  working,
  onOpen,
}: {
  room: HostRoom;
  working: boolean;
  onOpen: () => void;
}) {
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
        <div><dt>Questions</dt><dd>{room.questions.length}</dd></div>
        <div><dt>Response time</dt><dd>{formatDuration(room.durationMinutes ?? 20)}</dd></div>
        <div><dt>Reference files</dt><dd>{room.materials.length}</dd></div>
      </dl>
      <section className={styles.questionPreview}>
        <h2>Questions</h2>
        <ol>
          {room.questions.map((question) => <li key={question.id}>{question.prompt}</li>)}
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
}: {
  room: HostRoom;
  inviteUrl: string;
  copied: "code" | "link" | null;
  working: boolean;
  onCopy: (value: string, type: "code" | "link") => void;
  onStart: () => void;
  onRemove: (participantId: string) => void;
}) {
  const minimum = room.groupSize.minimum;
  const feasibleCapacity = hasFeasibleGroupCount(
    room.progress.participantCount,
    room.groupSize.minimum,
    room.groupSize.maximum,
  );
  const canStart = feasibleCapacity && room.allowedActions.includes("startActivity");
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
            <div><dt>Joined</dt><dd>{room.progress.participantCount}</dd></div>
            <div><dt>Response window</dt><dd>{formatDuration(room.durationMinutes ?? 20)}</dd></div>
            <div><dt>Questions</dt><dd>{room.questions.length}</dd></div>
          </dl>
          <Button fullWidth loading={working} onClick={onStart} disabled={!canStart}>
            Start activity
          </Button>
          {room.progress.participantCount < minimum ? (
            <p>At least {minimum} participants must join before the activity can start.</p>
          ) : !feasibleCapacity ? (
            <p>
              {room.progress.participantCount} participants can’t be divided into groups of {room.groupSize.minimum}–{room.groupSize.maximum}. Wait for another participant or remove one.
            </p>
          ) : (
            <p>Starting freezes the participant list and begins everyone’s shared timer.</p>
          )}
        </section>
      </div>

      <ParticipantRoster room={room} canRemove onRemove={onRemove} />
    </div>
  );
}

function CollectionView({
  room,
  remaining,
  working,
  onEnd,
}: {
  room: HostRoom;
  remaining: number | null;
  working: boolean;
  onEnd: () => void;
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
          <span>{answered} of {total} question responses saved</span>
        </div>
        <strong>{percent}%</strong>
        <div className={styles.progressTrack} aria-hidden="true">
          <span style={{ width: `${percent}%` }} />
        </div>
      </section>

      {room.allowedActions.includes("startAnalysis") ? (
        <section className={styles.endResponses} aria-labelledby="end-responses-title">
          {confirmEnd ? (
            <>
              <div>
                <h2 id="end-responses-title">End responses now?</h2>
                <p>
                  Participants will be unable to make further changes. Junto will use every answer
                  saved so far and begin preparing groups immediately.
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

function AnalysisView() {
  return (
    <div className={styles.analysisView}>
      <p>Group preparation</p>
      <h1>Preparing groups</h1>
      <span>Junto is balancing the frozen participant roster into valid group sizes.</span>
      <div className={styles.analysisRule} aria-hidden="true"><span /></div>
      <p className={styles.analysisNote}>
        This build uses deterministic placeholder grouping. Semantic analysis and optimization are intentionally not implemented yet.
      </p>
    </div>
  );
}

function AllGroupsView({ room, result }: { room: HostRoom; result: HostGroupsResponse | null }) {
  if (!result) return <LoadingSkeleton count={7} label="Loading group rosters" />;
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

      <div className={styles.groupList}>
        {result.groups.map((group, index) => (
          <section key={group.id} aria-labelledby={`group-${group.id}`}>
            <div className={styles.groupTitleRow}>
              <h2 id={`group-${group.id}`}>Group {index + 1}</h2>
              <span>{group.members.length} members</span>
            </div>
            <ol>
              {group.members.map((member) => <li key={member.participantId}>{member.displayName}</li>)}
            </ol>
          </section>
        ))}
      </div>
    </div>
  );
}
