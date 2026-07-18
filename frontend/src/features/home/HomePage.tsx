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
          <h1 id="home-title">Better discussions start with what everyone knows.</h1>
          <p className={styles.lede}>
            Junto reads the ideas across a room’s responses, then forms groups whose members
            bring useful knowledge and different approaches to the same table.
          </p>
          <div className={styles.process} aria-label="How Junto works">
            <div>
              <strong>Ask</strong>
              <span>Share a short set of questions with the room.</span>
            </div>
            <div>
              <strong>Understand</strong>
              <span>Junto maps the ideas present in each response.</span>
            </div>
            <div>
              <strong>Discuss</strong>
              <span>Everyone receives a group built for the conversation.</span>
            </div>
          </div>
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
