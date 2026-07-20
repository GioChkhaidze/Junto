import styles from "./AppMark.module.css";

export function AppMark() {
  return (
    <span className={styles.root}>
      <span className={styles.mark} aria-hidden="true">
        J
      </span>
      <span className={styles.wordmark}>Junto</span>
    </span>
  );
}
