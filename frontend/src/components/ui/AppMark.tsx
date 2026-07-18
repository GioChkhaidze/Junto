import { type HTMLAttributes } from "react";
import styles from "./AppMark.module.css";

export interface AppMarkProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  compact?: boolean;
}

export function AppMark({ className, compact = false, ...props }: AppMarkProps) {
  return (
    <span
      {...props}
      className={[styles.root, className].filter(Boolean).join(" ")}
      aria-label={compact ? "Junto" : props["aria-label"]}
    >
      <span className={styles.mark} aria-hidden="true">
        J
      </span>
      {compact ? null : <span className={styles.wordmark}>Junto</span>}
    </span>
  );
}
