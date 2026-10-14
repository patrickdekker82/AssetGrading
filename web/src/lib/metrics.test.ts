import { describe, expect, it } from "vitest";
import { directionText, formatMetric, groupName } from "./metrics";

describe("metric formatting", () => {
  it("formats by unit", () => {
    expect(formatMetric(0.25, "ratio")).toBe("25%");
    expect(formatMetric(0.0004, "ratio")).toBe("0,04%");
    expect(formatMetric(2.5, "multiple")).toBe("2,5×");
    expect(formatMetric(null, "ratio")).toBe("–");
    expect(formatMetric(3, "years")).toBe("3 jaar");
  });

  it("names comparison groups and directions in Dutch", () => {
    expect(groupName("own_history")).toBe("eigen historie");
    expect(groupName("stock_general:Technologie")).toBe("sector Technologie");
    expect(groupName("stock_financial")).toBe("alle banken en verzekeraars");
    expect(groupName("etf:sp500")).toBe("ETF's op dezelfde index");
    expect(directionText("lower")).toBe("lager is beter");
  });
});
