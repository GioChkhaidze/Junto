import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AppShell } from "../../components/layout";
import { Button, Icon, Input } from "../../components/ui";
import { normalizeJoinCode } from "../../lib/format";
import styles from "./HomePage.module.css";

export function HomePage() {
  const navigate = useNavigate();
  const [joinCode, setJoinCode] = useState("");

  function join(event: FormEvent) {
    event.preventDefault();
    const code = normalizeJoinCode(joinCode);
    if (code) navigate(`/join/${code}`);
  }

  return (
    <AppShell variant="public">
      <div className={styles.layout}>
        <section className={styles.introduction} aria-labelledby="home-title">
          <div className={styles.introductionInner}>
            <p className={styles.productLine}>Questions in. Better conversations out.</p>
            <h1 id="home-title">Build each discussion from the ideas already in the room.</h1>
            <p className={styles.lede}>
              Create a timed question activity, collect individual thinking, and form groups with the strongest feasible
              coverage of the ideas and perspectives that matter.
            </p>
            <ol className={styles.process} aria-label="How Junto works">
              <li>
                <strong>Prepare</strong>
                <span>Write the questions, coverage goals, and shared response time.</span>
              </li>
              <li>
                <strong>Respond</strong>
                <span>Participants answer one question at a time and submit when finished.</span>
              </li>
              <li>
                <strong>Group</strong>
                <span>When everyone submits or time ends, Junto prepares and releases the groups.</span>
              </li>
            </ol>
          </div>
        </section>

        <section className={styles.entry} aria-labelledby="entry-title">
          <div className={styles.entryInner}>
            <p className={styles.entryIntro}>Choose how you’re entering the room.</p>
            <h2 id="entry-title">Open Junto</h2>
            <div className={styles.hostAction}>
              <div>
                <h3>Start an activity</h3>
                <p>Create the questions, set the time, and invite your room.</p>
              </div>
              <Link className={styles.primaryLink} to="/create">
                Create activity
                <Icon name="arrow-right" size={18} />
              </Link>
            </div>

            <div className={styles.rule}>
              <span>or join an activity</span>
            </div>

            <form className={styles.joinForm} onSubmit={join}>
              <label htmlFor="join-code">Invite code</label>
              <div className={styles.joinRow}>
                <Input
                  id="join-code"
                  aria-describedby="join-code-hint"
                  value={joinCode}
                  onChange={(event) => setJoinCode(normalizeJoinCode(event.target.value))}
                  placeholder="e.g. J7KM4P"
                  autoCapitalize="characters"
                  autoComplete="off"
                  spellCheck={false}
                />
                <Button type="submit" disabled={!joinCode.trim()}>
                  Continue
                </Button>
              </div>
              <p id="join-code-hint" className={styles.hint}>
                Get this code from the person hosting your activity.
              </p>
            </form>
            <p className={styles.accountNote}>No account, email address, or installation required.</p>
          </div>
        </section>
      </div>
    </AppShell>
  );
}
