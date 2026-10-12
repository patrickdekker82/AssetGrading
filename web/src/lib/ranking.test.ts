import { describe, expect, it } from "vitest";
import type { GradeRow } from "@/components/GradeBadge";
import { applyFilters, EMPTY_FILTERS, sortRows } from "./ranking";

function row(over: Partial<GradeRow>): GradeRow {
  return {
    id: "x", rank: 1, name: "X", ticker: "X", template: "Platform", status: "graded", letter: "B", letter_low: null,
    letter_high: null, score: 65, quality: 60, timing: 70, coverage: 0.7, peg_safety: null, price_eur: 1, labels: [],
    reason: null, plus: null, minus: null, letter_month_ago: null, in_list: true, exclusion: null, mcap_rank: 1,
    btc_relative: null, spark: [1, 2], watched: false, asset_class: "crypto", ...over,
  };
}

const rows = [
  row({ id: "a", rank: 1, name: "Alpha", letter: "B", score: 65 }),
  row({ id: "b", rank: 2, name: "Beta", letter: "A-", score: 76, template: "DeFi-protocol" }),
  row({ id: "c", rank: 3, name: "Gamma", status: "no_grade", letter: null, score: 50, coverage: 0.3 }),
];

describe("ranking sort", () => {
  it("sorts grades best first and puts rows without a grade last", () => {
    expect(sortRows(rows, "grade", -1).map((r) => r.id)).toEqual(["b", "a", "c"]);
    expect(sortRows(rows, "grade", 1).map((r) => r.id)).toEqual(["a", "b", "c"]);
  });

  it("never sorts a hidden score of a row without grade", () => {
    expect(sortRows(rows, "score", -1).map((r) => r.id)).toEqual(["b", "a", "c"]);
  });
});

describe("ranking filters", () => {
  it("filters on grade, text, template and minimum values", () => {
    expect(applyFilters(rows, { ...EMPTY_FILTERS, grade: "B+" }).map((r) => r.id)).toEqual(["b"]);
    expect(applyFilters(rows, { ...EMPTY_FILTERS, grade: "graded" }).map((r) => r.id)).toEqual(["a", "b"]);
    expect(applyFilters(rows, { ...EMPTY_FILTERS, text: { name: "defi" } }).map((r) => r.id)).toEqual(["b"]);
    expect(applyFilters(rows, { ...EMPTY_FILTERS, min: { coverage: 50 } }).map((r) => r.id)).toEqual(["a", "b"]);
    expect(applyFilters(rows, { ...EMPTY_FILTERS, template: "Platform" }).map((r) => r.id)).toEqual(["a", "c"]);
  });

  it("filters stocks on sector and country", () => {
    const stocks = [
      row({ id: "aapl", sector: "Technologie", country: "US", asset_class: "stock" }),
      row({ id: "asml-as", sector: "Technologie", country: "NL", asset_class: "stock" }),
      row({ id: "jpm", sector: "Financieel", country: "US", asset_class: "stock" }),
    ];
    expect(applyFilters(stocks, { ...EMPTY_FILTERS, sector: "Technologie" }).map((r) => r.id)).toEqual(["aapl", "asml-as"]);
    expect(applyFilters(stocks, { ...EMPTY_FILTERS, sector: "Technologie", country: "US" }).map((r) => r.id))
      .toEqual(["aapl"]);
  });
});
