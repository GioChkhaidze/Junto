import type { ReactNode } from "react";
import styles from "./EmptyState.module.css";

interface EmptyStateProps {
  title: ReactNode;
  description: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ action, description, icon, title }: EmptyStateProps) {
  return (
    <section className={styles.root}>
      {icon ? (
        <div className={styles.icon} aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <div className={styles.copy}>
        <h2 className={styles.title}>{title}</h2>
        <div className={styles.description}>{description}</div>
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  );
}
