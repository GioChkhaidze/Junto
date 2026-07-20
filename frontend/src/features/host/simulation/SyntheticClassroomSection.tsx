import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Button, Field, Select } from "../../../components/ui";
import type { SyntheticClassroomProjection, SyntheticResponseSource } from "../../../domain";
import styles from "./SyntheticClassroomSection.module.css";

interface SyntheticClassroomSectionProps {
  projection: SyntheticClassroomProjection;
  working: boolean;
  onConfigure?: (targetSize: number) => Promise<void>;
  onGenerate?: (source: SyntheticResponseSource) => Promise<void>;
}

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
  const sources = useMemo<SyntheticResponseSource[]>(() => {
    const available: SyntheticResponseSource[] = [];
    if (projection.patternedAvailable) available.push("patterned");
    if (projection.openRouterAvailable) available.push("openrouter");
    return available;
  }, [projection.openRouterAvailable, projection.patternedAvailable]);
  const [source, setSource] = useState<SyntheticResponseSource>(() => sources[0] ?? "patterned");

  useEffect(() => {
    if (!projection.targetSizes.includes(targetSize)) {
      setTargetSize(firstTarget(projection));
    }
  }, [projection, targetSize]);

  useEffect(() => {
    if (!sources.includes(source) && sources[0]) {
      setSource(sources[0]);
    }
  }, [source, sources]);

  if (
    !projection.enabled ||
    (projection.stage !== "lobby" && projection.stage !== "answering") ||
    (projection.stage === "answering" && projection.syntheticParticipantCount === 0)
  ) {
    return null;
  }

  function configure(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (targetSize > 0 && onConfigure) void onConfigure(targetSize);
  }

  function removeParticipants() {
    if (onConfigure) void onConfigure(0);
  }

  function generate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sources.includes(source) || !onGenerate) return;
    void onGenerate(source);
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
          {projection.syntheticParticipantCount > 0 ? (
            <p className={styles.currentState}>
              {projection.syntheticParticipantCount} simulated participants are in this room.
            </p>
          ) : null}
        </div>
        <form className={styles.controls} onSubmit={configure}>
          <Field label="Simulated roster size" hint="Updating the total replaces only the simulated roster.">
            <Select
              value={targetSize || ""}
              onChange={(event) => setTargetSize(Number(event.currentTarget.value))}
              disabled={working || !projection.canConfigure || projection.targetSizes.length === 0}
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
            disabled={!projection.canConfigure || !onConfigure || targetSize === 0}
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
  const responseState = hasPendingParticipants
    ? `${projection.pendingSyntheticParticipantCount} of ${projection.syntheticParticipantCount} simulated ` +
      "participants still need to answer."
    : `All ${projection.syntheticParticipantCount} simulated participants have submitted.`;
  const selectedDescription =
    source === "openrouter"
      ? "OpenRouter models answer as distinct student profiles. Completing the roster starts analysis."
      : "Produces deterministic local fixtures for flow and load checks. It does not measure semantic accuracy.";

  return (
    <section className={styles.section} aria-labelledby="synthetic-classroom-title">
      <div className={styles.description}>
        <span>Development and demos</span>
        <h2 id="synthetic-classroom-title">Simulated responses</h2>
        <p>
          Generate answers for the simulated participants and submit them together. Nothing runs until you use the
          button.
        </p>
        <p className={styles.currentState}>{responseState}</p>
      </div>
      {hasPendingParticipants && sources.length > 0 ? (
        <form className={styles.controls} onSubmit={generate}>
          <Field label="Response source" hint={selectedDescription}>
            <Select
              value={source}
              onChange={(event) => setSource(event.currentTarget.value as SyntheticResponseSource)}
              disabled={working || !projection.canGenerate || !onGenerate}
            >
              {projection.patternedAvailable ? <option value="patterned">Patterned local responses</option> : null}
              {projection.openRouterAvailable ? (
                <option value="openrouter">OpenRouter generated responses</option>
              ) : null}
            </Select>
          </Field>
          <Button
            type="submit"
            variant="secondary"
            loading={working}
            loadingLabel="Generating responses"
            disabled={!projection.canGenerate || !onGenerate}
          >
            {source === "openrouter" ? "Generate with OpenRouter and submit" : "Generate and submit responses"}
          </Button>
        </form>
      ) : null}
    </section>
  );
}
