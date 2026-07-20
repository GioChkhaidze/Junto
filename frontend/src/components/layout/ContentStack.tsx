import type { HTMLAttributes } from "react";
import styles from "./ContentStack.module.css";

type ContentStackSpacing = "compact" | "default" | "section";

interface ContentStackProps extends HTMLAttributes<HTMLDivElement> {
  spacing?: ContentStackSpacing;
}

export function ContentStack({ className, spacing = "default", ...props }: ContentStackProps) {
  return <div {...props} className={[styles.stack, styles[spacing], className].filter(Boolean).join(" ")} />;
}

export function ContentActions({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={[styles.actions, className].filter(Boolean).join(" ")} />;
}
