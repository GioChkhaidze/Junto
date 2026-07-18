import { useId, type ReactNode, type SVGProps } from "react";

export type IconName =
  | "alert-circle"
  | "arrow-left"
  | "arrow-right"
  | "check"
  | "chevron-down"
  | "clock"
  | "close"
  | "copy"
  | "file"
  | "info"
  | "plus"
  | "refresh"
  | "trash"
  | "upload"
  | "users"
  | "warning";

const paths: Record<IconName, ReactNode> = {
  "alert-circle": (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.8v4.8" />
      <path d="M12 16.2h.01" />
    </>
  ),
  "arrow-left": (
    <>
      <path d="m14.5 5-7 7 7 7" />
      <path d="M8 12h9" />
    </>
  ),
  "arrow-right": (
    <>
      <path d="m9.5 5 7 7-7 7" />
      <path d="M16 12H7" />
    </>
  ),
  check: <path d="m5 12.5 4.2 4.2L19 7" />,
  "chevron-down": <path d="m7 9.5 5 5 5-5" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.2 2" />
    </>
  ),
  close: (
    <>
      <path d="m7 7 10 10" />
      <path d="M17 7 7 17" />
    </>
  ),
  copy: (
    <>
      <rect x="8" y="8" width="10" height="11" rx="1.5" />
      <path d="M16 8V5H6v11h2" />
    </>
  ),
  file: (
    <>
      <path d="M7 3h6l4 4v14H7z" />
      <path d="M13 3v5h4" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6" />
      <path d="M12 7h.01" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  refresh: (
    <>
      <path d="M19 8V4l-2 2a8 8 0 1 0 2.2 8" />
      <path d="M19 4h-4" />
    </>
  ),
  trash: (
    <>
      <path d="M5 7h14" />
      <path d="M9 7V4h6v3" />
      <path d="m7 7 .8 14h8.4L17 7" />
      <path d="M10 11v6M14 11v6" />
    </>
  ),
  upload: (
    <>
      <path d="M12 16V4" />
      <path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
      <path d="M5 15v5h14v-5" />
    </>
  ),
  users: (
    <>
      <circle cx="9" cy="8" r="3" />
      <path d="M3.5 19c.4-3.3 2.2-5 5.5-5s5.1 1.7 5.5 5" />
      <path d="M15 5.5a3 3 0 0 1 0 5.8" />
      <path d="M16 14c2.7.2 4.2 1.8 4.5 4.5" />
    </>
  ),
  warning: (
    <>
      <path d="M12 3 2.8 20h18.4z" />
      <path d="M12 9v4.5" />
      <path d="M12 17h.01" />
    </>
  ),
};

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  name: IconName;
  size?: number;
  title?: string;
}

export function Icon({ name, size = 20, title, ...props }: IconProps) {
  const generatedTitleId = useId();
  const titleId = title ? `icon-${generatedTitleId}` : undefined;

  return (
    <svg
      {...props}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      focusable="false"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-labelledby={titleId}
    >
      {title ? <title id={titleId}>{title}</title> : null}
      {paths[name]}
    </svg>
  );
}
