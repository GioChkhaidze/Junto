import { useEffect, useRef } from "react";

interface PollingOptions {
  enabled?: boolean;
  intervalMs?: number;
  runImmediately?: boolean;
}

export function usePolling(
  callback: () => Promise<void> | void,
  { enabled = true, intervalMs = 2000, runImmediately = false }: PollingOptions = {},
): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    let timeoutId: number | undefined;

    const run = async () => {
      try {
        await callbackRef.current();
      } finally {
        if (active) timeoutId = window.setTimeout(run, intervalMs);
      }
    };

    if (runImmediately) void run();
    else timeoutId = window.setTimeout(run, intervalMs);

    return () => {
      active = false;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [enabled, intervalMs, runImmediately]);
}
