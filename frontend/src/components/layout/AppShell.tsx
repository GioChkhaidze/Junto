import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AppMark, Icon } from "../ui";
import styles from "./AppShell.module.css";

interface AppShellProps {
  children: ReactNode;
  context?: string;
  actions?: ReactNode;
  wide?: boolean;
  quietHeader?: boolean;
}

export function AppShell({
  children,
  context,
  actions,
  wide = false,
  quietHeader = false,
}: AppShellProps) {
  return (
    <div className={styles.shell}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className={`${styles.header} ${quietHeader ? styles.quiet : ""}`}>
        <div className={styles.headerInner}>
          <Link className={styles.brandLink} to="/" aria-label="Junto home">
            <AppMark />
          </Link>
          {context ? (
            <>
              <span className={styles.divider} aria-hidden="true" />
              <span className={styles.context}>{context}</span>
            </>
          ) : null}
          {actions ? <div className={styles.actions}>{actions}</div> : null}
        </div>
      </header>
      <main
        id="main-content"
        className={`${styles.main} ${wide ? styles.mainWide : styles.mainReading}`}
      >
        {children}
      </main>
    </div>
  );
}

export function ConnectionBanner({ online }: { online: boolean }) {
  if (online) return null;
  return (
    <div className={styles.connectionBanner} role="status">
      <Icon name="warning" size={18} />
      You’re offline. Your current answer stays in this browser until the connection returns.
    </div>
  );
}
