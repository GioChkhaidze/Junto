import styles from "./LoadingSkeleton.module.css";

interface LoadingSkeletonProps {
  count?: number;
  label?: string;
}

export function LoadingSkeleton({ count = 1, label = "Loading content" }: LoadingSkeletonProps) {
  const safeCount = Math.max(1, Math.min(count, 12));

  return (
    <div className={styles.group} role="status" aria-label={label}>
      {Array.from({ length: safeCount }, (_, index) => (
        <span
          className={styles.line}
          key={index}
          style={index === safeCount - 1 && safeCount > 1 ? { width: "72%" } : undefined}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}
