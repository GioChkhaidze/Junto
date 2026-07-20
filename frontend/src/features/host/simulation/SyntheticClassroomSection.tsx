import { useEffect, useState, type FormEvent } from "react";
import { Button, Field, Select } from "../../../components/ui";
import type { SyntheticClassroomProjection } from "../../../domain";
import styles from "./SyntheticClassroomSection.module.css";

interface SyntheticClassroomSectionProps {
  projection: SyntheticClassroomProjection;
  working: boolean;
  onConfigure?: (targetSize: number) => Promise<void>;
  onGenerate?: () => Promise<void>;
}

const openRouterDisclosure =
  "OpenRouter receives the activity title, question prompts, anonymous behavioral profiles, and uploaded or pasted " +
  "room-wide source text. Participant names and IDs, coverage units, and host-only notes are not sent.";

function firstTarget(projection: SyntheticClassroomProjection): number {
  if (projection.targetSizes.includes(projection.syntheticParticipantCount)) {
    return projection.syntheticParticipantCount;
  }
  return projection.targetSizes[0] ?? 0;
}

export function SyntheticClassroomSection({
  projection,
  working,
  onConfigure,
  onGenerate,
}: SyntheticClassroomSectionProps) {
  const [targetSize, setTargetSize] = useState(() => firstTarget(projection));
  const [generationStartedAt, setGenerationStartedAt] = useState<number | null>(null);
  const generation = projection.generation;

  useEffect(() => {
    if (!projection.targetSizes.includes(targetSize)) {
      setTargetSize(firstTarget(projection));
    }
  }, [projection, targetSize]);

  if (
    !projection.enabled ||
    (projection.stage !== "lobby" && projection.stage !== "answering") ||
    (projection.stage === "answering" && projection.syntheticParticipantCount === 0)
  ) {
    return null;
  }

  function configure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (targetSize > 0 && projection.openRouterAvailable && onConfigure) void onConfigure(targetSize);
  }

  function removeParticipants() {
    if (onConfigure) void onConfigure(0);
  }

  async function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projection.openRouterAvailable || !onGenerate) return;
    setGenerationStartedAt(Date.now());
    try {
      await onGenerate();
    } finally {
      setGenerationStartedAt(null);
    }
  }

  if (projection.stage === "lobby") {
    return (
      <section className={styles.section} aria-labelledby="synthetic-classroom-title">
        <div className={styles.description}>
          <span>Development and demos</span>
          <h2 id="synthetic-classroom-title">Simulated participants</h2>
          <p>
            Add a varied test roster now. These participants wait in the lobby and do not answer until you explicitly
            run them after the activity starts.
          </p>
          {projection.openRouterAvailable ? <p className={styles.disclosure}>{openRouterDisclosure}</p> : null}
          {!projection.openRouterAvailable ? (
            <p className={styles.currentState} role="status">
              {projection.syntheticParticipantCount > 0
                ? "OpenRouter is not configured. Remove this simulated roster before starting the activity."
                : "OpenRouter is not configured, so simulated participants cannot be added to this room."}
            </p>
          ) : null}
          {projection.syntheticParticipantCount > 0 ? (
            <p className={styles.currentState}>
              {projection.syntheticParticipantCount} simulated participants are in this room.
            </p>
          ) : null}
        </div>
        <form className={styles.controls} onSubmit={configure}>
          <Field
            label="Simulated roster size"
            hint={
              projection.openRouterAvailable
                ? "Updating the total replaces only the simulated roster."
                : "Configure OpenRouter before adding simulated participants."
            }
          >
            <Select
              value={targetSize || ""}
              onChange={(event) => setTargetSize(Number(event.currentTarget.value))}
              disabled={
                working ||
                !projection.canConfigure ||
                !projection.openRouterAvailable ||
                projection.targetSizes.length === 0
              }
            >
              {projection.targetSizes.length === 0 ? <option value="">No feasible roster size</option> : null}
              {projection.targetSizes.map((size) => (
                <option key={size} value={size}>
                  {size} participants
                </option>
              ))}
            </Select>
          </Field>
          <Button
            type="submit"
            variant="secondary"
            loading={working}
            loadingLabel="Updating participants"
            disabled={!projection.canConfigure || !projection.openRouterAvailable || !onConfigure || targetSize === 0}
          >
            {projection.syntheticParticipantCount > 0 ? "Update participants" : "Add participants"}
          </Button>
          {projection.syntheticParticipantCount > 0 ? (
            <Button
              type="button"
              variant="quiet"
              disabled={working || !projection.canConfigure || !onConfigure}
              onClick={removeParticipants}
            >
              Remove simulated participants
            </Button>
          ) : null}
        </form>
      </section>
    );
  }

  const hasPendingParticipants = projection.pendingSyntheticParticipantCount > 0;
  const isGenerating = generation?.status === "running" || generationStartedAt !== null;
  const responseState = hasPendingParticipants
    ? `${projection.syntheticParticipantCount - projection.pendingSyntheticParticipantCount} of ` +
      `${projection.syntheticParticipantCount} simulated participants have submitted.`
    : `All ${projection.syntheticParticipantCount} simulated participants have submitted.`;
  return (
    <section className={styles.section} aria-labelledby="synthetic-classroom-title">
      <div className={styles.description}>
        <span>Development and demos</span>
        <h2 id="synthetic-classroom-title">Simulated responses</h2>
        <p>
          {openRouterDisclosure} Generated responses can be incomplete or mistaken. Nothing runs until you use the
          button.
        </p>
        <p className={styles.currentState}>{responseState}</p>
      </div>
      {hasPendingParticipants && projection.openRouterAvailable ? (
        <form className={styles.controls} onSubmit={generate}>
          <div className={styles.providerSummary}>
            <h3>OpenRouter student simulation</h3>
            <p>Responses are saved as students finish. When the complete roster submits, analysis starts.</p>
          </div>
          {generation?.status === "failed" && generation.error ? (
            <p className={styles.generationError} role="alert">
              {generation.error}
            </p>
          ) : null}
          <Button
            type="submit"
            variant="secondary"
            loading={working || isGenerating}
            loadingLabel="Generating responses"
            disabled={!projection.canGenerate || !onGenerate || isGenerating}
          >
            {generation?.status === "failed" ? "Retry remaining students" : "Generate with OpenRouter and submit"}
          </Button>
        </form>
      ) : hasPendingParticipants ? (
        <div className={styles.providerSummary} role="status">
          <h3>Response generation unavailable</h3>
          <p>
            OpenRouter is not configured for this server. Simulated participants remain waiting; Junto will not submit
            placeholder answers in their place.
          </p>
        </div>
      ) : null}
    </section>
  );
}
