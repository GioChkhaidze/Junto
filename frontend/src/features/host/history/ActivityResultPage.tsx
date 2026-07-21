import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../../api";
import { AppShell, HeaderLink } from "../../../components/layout";
import { InlineNotice, LoadingSkeleton } from "../../../components/ui";
import type { PublishedActivity } from "../../../domain";
import { useDocumentTitle } from "../../../hooks/useDocumentTitle";
import { HostResults } from "../results/HostResults";
import styles from "./ActivityResultPage.module.css";

export function ActivityResultPage() {
  const { roomId = "" } = useParams<{ roomId: string }>();
  const [activity, setActivity] = useState<PublishedActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  useDocumentTitle(activity?.title ?? "Activity results");

  useEffect(() => {
    const controller = new AbortController();
    api
      .getPublishedActivity(roomId, controller.signal)
      .then(setActivity)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "The activity results could not load.");
        }
      });
    return () => controller.abort();
  }, [roomId]);

  return (
    <AppShell
      context={activity?.title ?? "Activity results"}
      variant="host"
      actions={<HeaderLink to="/activities">Activities</HeaderLink>}
    >
      <div className={styles.page}>
        {error ? (
          <InlineNotice tone="error" title="Results unavailable">
            {error}
          </InlineNotice>
        ) : activity ? (
          <HostResults room={{ progress: { participantCount: activity.participantCount } }} result={activity.result} />
        ) : (
          <LoadingSkeleton count={8} label="Loading activity results" />
        )}
      </div>
    </AppShell>
  );
}
