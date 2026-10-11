import { describe, expect, it } from "vitest";
import { formatDuration, formatNumber } from "./format";

describe("format", () => {
  it("formats durations in Dutch units", () => {
    expect(formatDuration("2026-10-11T00:05:00Z", "2026-10-11T00:05:42Z")).toBe("42 s");
    expect(formatDuration("2026-10-11T00:05:00Z", "2026-10-11T00:08:10Z")).toBe("3 min 10 s");
    expect(formatDuration("2026-10-11T00:05:00Z", null)).toBe("loopt");
  });

  it("uses Dutch number grouping and shows a dash for missing values", () => {
    expect(formatNumber(10000)).toBe("10.000");
    expect(formatNumber(null)).toBe("–");
  });
});
