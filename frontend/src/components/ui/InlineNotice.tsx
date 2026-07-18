import { type HTMLAttributes, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import styles from "./InlineNotice.module.css";

export type NoticeTone = "info" | "success" | "warning" | "error";

export interface InlineNoticeProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  tone?: NoticeTone;
  title?: ReactNode;
  children: ReactNode;
}

const toneIcon: Record<NoticeTone, IconName> = {
  info: "info",
  success: "check",
  warning: "warning",
  error: "alert-circle",
};

export function InlineNotice({
  children,
  className,
  role,
  title,
  tone = "info",
  ...props
}: InlineNoticeProps) {
  return (
    <div
      {...props}
      role={role ?? (tone === "error" ? "alert" : undefined)}
      className={[styles.notice, styles[tone], className].filter(Boolean).join(" ")}
    >
      <Icon className={styles.icon} name={toneIcon[tone]} size={20} />
      <div className={styles.content}>
        {title ? <div className={styles.title}>{title}</div> : null}
        <div className={styles.body}>{children}</div>
      </div>
    </div>
  );
}
