import { describe, expect, it } from "vitest";
import {
  formatCountdown,
  formatDuration,
  formatFileSize,
  normalizeJoinCode,
} from "../format";

describe("format helpers", () => {
  it("normalizes invite codes for room navigation", () => {
    expect(normalizeJoinCode(" j7-km 4p! ")).toBe("J7KM4P");
    expect(normalizeJoinCode("1234567890")).toBe("12345678");
  });

  it("formats countdowns without allowing negative display values", () => {
    expect(formatCountdown(65.9)).toBe("1:05");
    expect(formatCountdown(3_661)).toBe("1:01:01");
    expect(formatCountdown(-4)).toBe("0:00");
  });

  it("keeps supporting labels concise and human-readable", () => {
    expect(formatDuration(1)).toBe("1 minute");
    expect(formatDuration(75)).toBe("1 hr 15 min");
    expect(formatFileSize(1_572_864)).toBe("1.5 MB");
  });
});
