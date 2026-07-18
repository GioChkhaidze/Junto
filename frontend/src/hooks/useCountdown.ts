import { useEffect, useMemo, useState } from "react";

export function useCountdown(deadline?: string | null): number | null {
  const deadlineMs = useMemo(() => {
    if (!deadline) return null;
    const parsed = Date.parse(deadline);
    return Number.isFinite(parsed) ? parsed : null;
  }, [deadline]);
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
