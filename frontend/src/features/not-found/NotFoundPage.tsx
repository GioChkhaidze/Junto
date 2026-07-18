import { Link } from "react-router-dom";
import { AppShell } from "../../components/layout";
import styles from "./NotFoundPage.module.css";

export function NotFoundPage() {
  return (
    <AppShell>
      <div className={styles.page}>
        <p className={styles.code}>404</p>
        <h1>This page isn’t part of the room.</h1>
        <p>Check the address or return to Junto to create or join an activity.</p>
        <Link to="/">Return to Junto</Link>
      </div>
    </AppShell>
  );
}
