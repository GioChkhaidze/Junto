import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AppMark, Icon } from "../ui";
import styles from "./AppShell.module.css";

interface AppShellProps {
  children: ReactNode;
  context?: string;
  actions?: ReactNode;
  wide?: boolean;
  variant?: "default" | "authoring" | "host" | "public";
}

interface HeaderLinkProps {
  children: ReactNode;
  to: string;
}

export function AppShell({ children, context, actions, wide = false, variant = "default" }: AppShellProps) {
  const authoring = variant === "authoring";
  const host = variant === "host";
  const publicPage = variant === "public";
  const darkHeader = authoring || host || publicPage;
  const mainClass = authoring
    ? styles.mainAuthoring
    : publicPage
      ? styles.mainPublic
      : host
        ? styles.mainHost
        : wide
          ? styles.mainWide
          : styles.mainReading;
  return (
    <div className={publicPage ? `${styles.shell} ${styles.publicShell}` : styles.shell}>
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <header className={`${styles.header} ${darkHeader ? styles.darkHeader : ""}`}>
        <div className={`${styles.headerInner} ${darkHeader ? styles.darkHeaderInner : ""}`}>
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
      <main id="main-content" className={`${styles.main} ${mainClass}`}>
        {children}
      </main>
    </div>
  );
}

export function HeaderLink({ children, to }: HeaderLinkProps) {
  return (
    <Link className={styles.headerLink} to={to}>
      {children}
    </Link>
  );
}

export function ConnectionBanner({ online }: { online: boolean }) {
  if (online) return null;
  return (
    <div className={styles.connectionBanner} role="status">
      <Icon name="warning" size={18} />
      You’re offline. Reconnect before leaving this question so Junto can save your changes.
    </div>
  );
}
