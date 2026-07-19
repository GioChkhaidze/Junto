import { type FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, ApiError } from "../../../api";
import { AppShell } from "../../../components/layout";
import {
  Button,
  Field,
  InlineNotice,
  Input,
  LoadingSkeleton,
} from "../../../components/ui";
import type { PublicJoinRoom } from "../../../domain";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { normalizeJoinCode } from "../../../lib/format";
import styles from "./JoinRoomPage.module.css";

function readableError(error: unknown): string {
  if (error instanceof ApiError && error.status === 404) {
    return "This invite code isn’t open. Check the code with the host.";
  }
  if (error instanceof Error) return error.message;
  return "Junto couldn’t open this invitation.";
}

export function JoinRoomPage() {
  const params = useParams<{ joinCode: string }>();
  const navigate = useNavigate();
  const joinCode = normalizeJoinCode(params.joinCode ?? "");
  const [room, setRoom] = useState<PublicJoinRoom | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useDocumentTitle(room?.title ? `Join ${room.title}` : "Join activity");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .lookupJoinCode(joinCode, controller.signal)
      .then(setRoom)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(readableError(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [joinCode]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!displayName.trim() || !room) return;
    setJoining(true);
    setError(null);
    try {
      const participant = await api.joinRoom(joinCode, { displayName: displayName.trim() });
      navigate(`/room/${participant.roomId}`, { replace: true });
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setJoining(false);
    }
  }

  return (
    <AppShell context={room?.title ?? "Join activity"}>
      <div className={styles.joinPage}>
        {loading ? (
          <div aria-label="Loading invitation">
            <LoadingSkeleton count={4} />
          </div>
        ) : error && !room ? (
          <>
            <h1>Invitation unavailable</h1>
            <InlineNotice tone="error" title="You can’t join with this code">
              {error}
            </InlineNotice>
            <Button variant="secondary" onClick={() => navigate("/")}>
              Enter another code
            </Button>
          </>
        ) : room ? (
          <>
            <header className={styles.header}>
              <p className={styles.inviteLine}>You’ve been invited to</p>
              <h1>{room.title}</h1>
              <p>Enter the name your group should recognize. No account is required.</p>
            </header>

            <form className={styles.form} onSubmit={submit}>
              <Field
                label="Your name"
                hint="Your name is visible to the host and your eventual group."
                error={displayName.length > 0 && displayName.trim().length < 2 ? "Enter at least 2 characters." : undefined}
                required
              >
                <Input
                  autoFocus
                  autoComplete="name"
                  maxLength={80}
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="e.g. Maya Chen"
                />
              </Field>

              <div className={styles.disclosure}>
                <p>
                  Junto stores your room name and answers for this activity. This prototype does
                  not send answers to an external AI service. Don’t include sensitive personal information.
                </p>
              </div>

              {error ? (
                <InlineNotice tone="error" title="Couldn’t join">
                  {error}
                </InlineNotice>
              ) : null}
              <Button
                type="submit"
                fullWidth
                loading={joining}
                loadingLabel="Joining activity"
                disabled={displayName.trim().length < 2}
              >
                Join activity
              </Button>
            </form>
            <p className={styles.codeLine}>
              Invite code <strong>{joinCode}</strong>
            </p>
          </>
        ) : null}
      </div>
    </AppShell>
  );
}
