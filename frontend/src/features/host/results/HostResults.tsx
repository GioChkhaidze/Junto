import { useState } from "react";
import { LoadingSkeleton } from "../../../components/ui";
import type {
  CoverageAwareHostGroupsResponse,
  GroupQuestionResult,
  HostGroupsResponse,
  HostRoom,
} from "../../../domain";
import styles from "./HostResults.module.css";

interface HostResultsProps {
  room: HostRoom;
  result: HostGroupsResponse | null;
}

function memberNames(members: Array<{ displayName: string }>): string {
  return members.map((member) => member.displayName).join(", ");
}

function resultScale(room: HostRoom, result: HostGroupsResponse): string {
  const groups = `${result.groups.length} ${result.groups.length === 1 ? "group" : "groups"}`;
  const participants = room.progress.participantCount;
  return `${groups} · ${participants} ${participants === 1 ? "participant" : "participants"}`;
}

function resultTruth(result: CoverageAwareHostGroupsResponse): string {
  const complete = result.coverageReport.fullyCoveredGroupQuestions;
  const total = result.coverageReport.totalGroupQuestions;
  const coverage = `${complete} of ${total} group questions have complete coverage.`;
  if (result.solver.status === "fallback") return `${coverage} A capacity-valid fallback was used.`;
  if (result.solver.completeCoverageStatus === "infeasible") {
    return `${coverage} Complete coverage was not possible for every group.`;
  }
  if (result.solver.completeCoverageStatus === "unknown") {
    return `${coverage} Complete-coverage feasibility was not resolved.`;
  }
  return coverage;
}

function unitNumbers(question: GroupQuestionResult, coveredUnitIds: string[]): string {
  const numbers = coveredUnitIds
    .map((unitId) => question.units.findIndex((unit) => unit.id === unitId) + 1)
    .filter((position) => position > 0);
  return numbers.length ? numbers.join(", ") : "None";
}

function QuestionDetail({ groupId, question }: { groupId: string; question: GroupQuestionResult }) {
  const [answersVisible, setAnswersVisible] = useState(false);
  const unclassified = question.responseAudit
    .filter((response) => response.family === null)
    .map((response) => response.participant);
  const covered = question.units.filter((unit) => unit.covered).length;
  const answerRegionId = `${groupId}-${question.questionId}-answers`;

  return (
    <div className={styles.questionDetail}>
      <section aria-labelledby={`${groupId}-${question.questionId}-coverage`}>
        <div className={styles.detailHeading}>
          <h3 id={`${groupId}-${question.questionId}-coverage`}>Coverage</h3>
          <span>
            {covered} of {question.units.length} represented
          </span>
        </div>
        <ol className={styles.coverageList}>
          {question.units.map((unit, index) => (
            <li key={unit.id} data-covered={unit.covered}>
              <span className={styles.unitNumber}>{index + 1}</span>
              <div>
                <strong>{unit.text}</strong>
                <span>
                  {unit.carriers.length
                    ? `Supported by ${memberNames(unit.carriers)}`
                    : "Not represented in this group"}
                </span>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.families} aria-labelledby={`${groupId}-${question.questionId}-families`}>
        <h3 id={`${groupId}-${question.questionId}-families`}>Response families</h3>
        {question.representedFamilies.length || unclassified.length ? (
          <dl>
            {question.representedFamilies.map((family) => (
              <div key={family.id}>
                <dt>{family.label}</dt>
                <dd>{memberNames(family.members)}</dd>
              </div>
            ))}
            {unclassified.length ? (
              <div>
                <dt>No clear family</dt>
                <dd>{memberNames(unclassified)}</dd>
              </div>
            ) : null}
          </dl>
        ) : (
          <p>No response family was identified for this group.</p>
        )}
      </section>

      <button
        type="button"
        className={styles.answerToggle}
        aria-expanded={answersVisible}
        aria-controls={answerRegionId}
        onClick={() => setAnswersVisible((visible) => !visible)}
      >
        {answersVisible ? "Hide answer classifications" : "Show answer classifications"}
      </button>

      {answersVisible ? (
        <ul id={answerRegionId} className={styles.answerList}>
          {question.responseAudit.map((response) => (
            <li key={response.participant.participantId}>
              <header>
                <strong>{response.participant.displayName}</strong>
                <span>{response.family?.label ?? "No clear family"}</span>
              </header>
              <p>Covered units: {unitNumbers(question, response.coveredUnitIds)}</p>
              <blockquote>{response.answer ?? "No answer submitted."}</blockquote>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CoverageAwareResults({ room, result }: { room: HostRoom; result: CoverageAwareHostGroupsResponse }) {
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [openQuestionKey, setOpenQuestionKey] = useState<string | null>(null);

  function toggleGroup(groupId: string) {
    setOpenGroupId((current) => (current === groupId ? null : groupId));
    setOpenQuestionKey(null);
  }

  return (
    <div className={styles.results}>
      <header className={styles.resultsHeader}>
        <h1>Groups</h1>
        <p>{resultScale(room, result)}</p>
        <span>{resultTruth(result)}</span>
      </header>

      <div className={styles.groupList}>
        {result.groups.map((group, groupIndex) => {
          const groupOpen = group.id === openGroupId;
          const groupRegionId = `${group.id}-questions`;
          return (
            <section key={group.id} aria-labelledby={`${group.id}-label`}>
              <button
                id={`${group.id}-label`}
                type="button"
                className={styles.groupRow}
                aria-expanded={groupOpen}
                aria-controls={groupRegionId}
                onClick={() => toggleGroup(group.id)}
              >
                <strong>Group {groupIndex + 1}:</strong> {memberNames(group.members)}
              </button>
              {groupOpen ? (
                <div id={groupRegionId} className={styles.groupDetail}>
                  {group.questions.map((question) => {
                    const questionKey = `${group.id}:${question.questionId}`;
                    const questionOpen = openQuestionKey === questionKey;
                    const questionRegionId = `${group.id}-${question.questionId}`;
                    const covered = question.units.filter((unit) => unit.covered).length;
                    return (
                      <section key={question.questionId} aria-labelledby={`${questionRegionId}-label`}>
                        <button
                          id={`${questionRegionId}-label`}
                          type="button"
                          className={styles.questionRow}
                          aria-expanded={questionOpen}
                          aria-controls={questionRegionId}
                          onClick={() => setOpenQuestionKey(questionOpen ? null : questionKey)}
                        >
                          <span>
                            <strong>Question {question.position + 1}:</strong> {question.prompt}
                          </span>
                          <small>
                            {covered} of {question.units.length} units represented
                          </small>
                        </button>
                        {questionOpen ? (
                          <div id={questionRegionId}>
                            <QuestionDetail groupId={group.id} question={question} />
                          </div>
                        ) : null}
                      </section>
                    );
                  })}
                </div>
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}

export function HostResults({ room, result }: HostResultsProps) {
  if (!result) return <LoadingSkeleton count={7} label="Loading group rosters" />;
  if (result.generationMode === "coverage_aware") return <CoverageAwareResults room={room} result={result} />;
  return (
    <div className={styles.results}>
      <header className={styles.resultsHeader}>
        <h1>Groups</h1>
        <p>{resultScale(room, result)}</p>
        <span>Responses were not interpreted in this room.</span>
      </header>
      <ol className={styles.placeholderGroups}>
        {result.groups.map((group, index) => (
          <li key={group.id}>
            <strong>Group {index + 1}:</strong> {memberNames(group.members)}
          </li>
        ))}
      </ol>
    </div>
  );
}
