import { createElement, type HTMLAttributes, type ReactNode } from "react";
import styles from "./EmptyState.module.css";

export interface EmptyStateProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title: ReactNode;
  description: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  headingLevel?: 2 | 3;
}

export function EmptyState({
  action,
  className,
  description,
  headingLevel = 2,
  icon,
  title,
  ...props
}: EmptyStateProps) {
  return (
    <section {...props} className={[styles.root, className].filter(Boolean).join(" ")}>
      {icon ? (
        <div className={styles.icon} aria-hidden="true">
          {icon}
        </div>
      ) : null}
      <div className={styles.copy}>
        {createElement(`h${headingLevel}`, { className: styles.title }, title)}
        <div className={styles.description}>{description}</div>
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </section>
  );
}
