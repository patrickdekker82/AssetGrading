import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { lookup } from "./glossary";
import { isTabSlug, RANKING_COLUMNS, TABS } from "./tabs";

const configDir = path.resolve(import.meta.dirname, "../../../config");

describe("tabs", () => {
  it("match the slugs in config/universes.yaml, in order", () => {
    const yaml = readFileSync(path.join(configDir, "universes.yaml"), "utf8");
    const slugs = [...yaml.matchAll(/^\s+- slug: (\w+)/gm)].map((m) => m[1]);
    expect(TABS.map((t) => t.slug)).toEqual(slugs);
  });

  it("recognises valid and invalid slugs", () => {
    expect(isTabSlug("crypto")).toBe(true);
    expect(isTabSlug("bitcoin")).toBe(false);
  });

  it("every column tooltip exists in the glossary file", () => {
    const yaml = readFileSync(path.join(configDir, "glossary.nl.yaml"), "utf8");
    for (const col of RANKING_COLUMNS) {
      if (col.term) expect(yaml).toMatch(new RegExp(`^  ${col.term}:`, "m"));
    }
  });
});

describe("glossary lookup", () => {
  const glossary = {
    terms: { score: { label: "Score", uitleg: "term" } },
    metrics: { score: { label: "Score", uitleg: "metric" }, beta: { label: "Bèta", uitleg: "b" } },
  };

  it("prefers terms over metrics", () => {
    expect(lookup(glossary, "score")?.uitleg).toBe("term");
  });

  it("falls back to metrics and returns undefined when unknown", () => {
    expect(lookup(glossary, "beta")?.label).toBe("Bèta");
    expect(lookup(glossary, "nope")).toBeUndefined();
  });
});
