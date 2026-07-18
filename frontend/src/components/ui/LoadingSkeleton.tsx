import { type CSSProperties, type HTMLAttributes } from "react";
import styles from "./LoadingSkeleton.module.css";

type SkeletonStyle = CSSProperties & {
  "--skeleton-height"?: string;
  "--skeleton-width"?: string;
};

export interface LoadingSkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, "children"> {
  count?: number;
  width?: string;
  height?: string;
  label?: string;
}

export function LoadingSkeleton({
  className,
  count = 1,
  height = "1rem",
  label = "Loading content",
  style,
  width = "100%",
  ...props
}: LoadingSkeletonProps) {
  const safeCount = Math.max(1, Math.min(count, 12));
  const skeletonStyle: SkeletonStyle = {
    ...style,
    "--skeleton-height": height,
    "--skeleton-width": width,
  };

  return (
    <div
      {...props}
      className={[styles.group, className].filter(Boolean).join(" ")}
      style={skeletonStyle}
      role="status"
      aria-label={label}
    >
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
