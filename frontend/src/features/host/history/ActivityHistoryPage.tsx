import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../../api";
import { AppShell, HeaderLink } from "../../../components/layout";
import { Button, Field, Input, LoadingSkeleton } from "../../../components/ui";
import type { ActivityHistory, ActivitySummary } from "../../../domain";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import styles from "./ActivityHistoryPage.module.css";

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function activityState(activity: ActivitySummary): string {
  if (activity.status === "published" && activity.generationMode === "coverage_aware") {
    return `${activity.fullyCoveredGroupQuestions ?? 0} of ${activity.totalGroupQuestions ?? 0} fully covered`;
  }
  if (activity.status === "published") return "Groups ready";
  if (activity.status === "draft") return "Draft";
  if (activity.status === "lobby") return "Invite lobby";
  if (activity.status === "answering") return "Responses open";
  if (activity.status === "analyzing") return "Preparing groups";
  return "Stopped";
}

function activityScale(activity: ActivitySummary): string {
  const participants = `${activity.participantCount} participant${activity.participantCount === 1 ? "" : "s"}`;
  if (activity.status !== "published") {
    return `${participants} · ${activity.questionCount} question${activity.questionCount === 1 ? "" : "s"}`;
  }
  return `${participants} · ${activity.groupCount} group${activity.groupCount === 1 ? "" : "s"}`;
}

function DeleteActivityDialog({
  activity,
  onClose,
  onDeleted,
}: {
  activity: ActivitySummary;
  onClose: () => void;
  onDeleted: (roomId: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirmed = confirmation.toUpperCase() === activity.joinCode;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || deleting) return;
    setDeleting(true);
    setError(null);
    try {
      await api.deleteRoom(activity.roomId, confirmation);
      onDeleted(activity.roomId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The activity could not be deleted.");
      setDeleting(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className={styles.deleteDialog}
      aria-labelledby="delete-activity-title"
      aria-describedby="delete-activity-description"
      onCancel={(event) => {
        event.preventDefault();
        if (!deleting) onClose();
      }}
    >
      <form onSubmit={(event) => void submit(event)}>
        <h2 id="delete-activity-title">Delete {activity.title}?</h2>
        <p id="delete-activity-description">This permanently removes the room, answers, and grouping result.</p>
        <Field
          label="Deletion password"
          hint={
            <>
              Enter the invite code <strong>{activity.joinCode}</strong>.
            </>
          }
          error={error}
          required
        >
          <Input
            autoFocus
            autoCapitalize="characters"
            autoComplete="off"
            maxLength={6}
            spellCheck={false}
            type="password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value.toUpperCase())}
          />
        </Field>
        <div className={styles.dialogActions}>
          <Button variant="secondary" disabled={deleting} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            type="submit"
            disabled={!confirmed}
            loading={deleting}
            loadingLabel="Deleting activity"
          >
            Delete activity
          </Button>
        </div>
      </form>
    </dialog>
  );
}

export function ActivityHistoryPage() {
  useDocumentTitle("Activities");
  const [history, setHistory] = useState<ActivityHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activityToDelete, setActivityToDelete] = useState<ActivitySummary | null>(null);
  const [requestKey, setRequestKey] = useState(0);

  const retry = useCallback(() => {
    setError(null);
    setHistory(null);
    setRequestKey((current) => current + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getActivities(controller.signal)
      .then(setHistory)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : "Activities could not load.");
      });
    return () => controller.abort();
  }, [requestKey]);

  return (
    <AppShell context="Activities" variant="host" actions={<HeaderLink to="/create">Create activity</HeaderLink>}>
      <div className={styles.page}>
        <header className={styles.heading}>
          <h1>Activities</h1>
          {history?.activities.length ? <span>{history.activities.length} saved</span> : null}
        </header>

        {error ? (
          <div className={styles.error} role="alert">
            <p>{error}</p>
            <Button variant="secondary" size="compact" onClick={retry}>
              Try again
            </Button>
          </div>
        ) : !history ? (
          <LoadingSkeleton count={6} label="Loading activities" />
        ) : history.activities.length === 0 ? (
          <section className={styles.empty}>
            <h2>No activities yet.</h2>
            <p>Create an activity to see its room and results here.</p>
            <Link to="/create">Create activity</Link>
          </section>
        ) : (
          <ol className={styles.activities}>
            {history.activities.map((activity) => (
              <li key={activity.roomId}>
                <Link
                  className={styles.activityLink}
                  to={activity.status === "published" ? `/activities/${activity.roomId}` : `/host/${activity.roomId}`}
                >
                  <span className={styles.identity}>
                    <strong>{activity.title}</strong>
                    <time dateTime={activity.createdAt}>{dateFormatter.format(new Date(activity.createdAt))}</time>
                  </span>
                  <span className={styles.scale}>{activityScale(activity)}</span>
                  <span className={styles.state} data-status={activity.status}>
                    {activityState(activity)}
                  </span>
                </Link>
                {activity.canDelete ? (
                  <button
                    type="button"
                    className={styles.deleteAction}
                    aria-label={`Delete ${activity.title}`}
                    onClick={() => setActivityToDelete(activity)}
                  >
                    Delete
                  </button>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
      {activityToDelete ? (
        <DeleteActivityDialog
          activity={activityToDelete}
          onClose={() => setActivityToDelete(null)}
          onDeleted={(roomId) => {
            setHistory((current) =>
              current ? { activities: current.activities.filter((activity) => activity.roomId !== roomId) } : current,
            );
            setActivityToDelete(null);
          }}
        />
      ) : null}
    </AppShell>
  );
}
