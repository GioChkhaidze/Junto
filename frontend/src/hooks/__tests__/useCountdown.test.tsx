import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useCountdown } from "../useCountdown";

describe("useCountdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-18T10:00:00.000Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down from a server-provided remaining duration", () => {
    const { result } = renderHook(() => useCountdown(null, null, 3));

    expect(result.current).toBe(3);

    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(result.current).toBe(2);

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(result.current).toBe(0);
  });

  it("uses server time to avoid relying on the participant's local clock", () => {
    const { result } = renderHook(() => useCountdown("2026-07-18T08:01:00.000Z", "2026-07-18T08:00:00.000Z", null));

    expect(result.current).toBe(60);
  });

  it("returns no countdown when timing data is unavailable", () => {
    const { result } = renderHook(() => useCountdown());

    expect(result.current).toBeNull();
  });
});
