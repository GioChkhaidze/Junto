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
    <AppShell wide quietHeader>
      <div className={styles.layout}>
        <section className={styles.introduction} aria-labelledby="home-title">
          <h1 id="home-title">A clear path from questions to discussion groups.</h1>
          <p className={styles.lede}>
            Junto runs a timed question activity from invitation to group roster. This build uses
            deterministic placeholder grouping while the response-aware engine is still being implemented.
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
              <span>When everyone submits or time ends, Junto releases the room roster.</span>
            </li>
          </ol>
        </section>

        <section className={styles.entry} aria-labelledby="entry-title">
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
        </section>
      </div>
    </AppShell>
  );
}
