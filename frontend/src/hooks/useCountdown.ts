import { useEffect, useMemo, useState } from "react";

export function useCountdown(
  deadline?: string | null,
  serverTime?: string | null,
  remainingSeconds?: number | null,
): number | null {
  const deadlineMs = useMemo(() => {
    if (typeof remainingSeconds === "number" && Number.isFinite(remainingSeconds)) {
      return Date.now() + Math.max(0, remainingSeconds) * 1000;
    }
    if (!deadline) return null;
    const parsed = Date.parse(deadline);
    if (!Number.isFinite(parsed)) return null;
    if (serverTime) {
      const serverNow = Date.parse(serverTime);
      if (Number.isFinite(serverNow)) return Date.now() + Math.max(0, parsed - serverNow);
    }
    return parsed;
  }, [deadline, remainingSeconds, serverTime]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (deadlineMs === null) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [deadlineMs]);

  if (deadlineMs === null) return null;
  return Math.max(0, Math.ceil((deadlineMs - now) / 1000));
}
