// Navigation order and labels. Kept in sync with config/universes.yaml (checked by tests on both sides).
export const TABS = [
  { slug: "crypto", label: "Crypto" },
  { slug: "stocks", label: "Aandelen" },
  { slug: "etfs", label: "ETF's" },
  { slug: "commodities", label: "Grondstoffen" },
  { slug: "fx", label: "Valuta" },
  { slug: "bonds", label: "Obligaties" },
  { slug: "indices", label: "Indices" },
  { slug: "watchlist", label: "Volglijst" },
  { slug: "model", label: "Model" },
] as const;

export type TabSlug = (typeof TABS)[number]["slug"];

/** The tab an asset class lives on (asset pages are /<tab>/<asset>). */
export function tabForClass(assetClass: string): string {
  return ({ crypto: "crypto", stock: "stocks", etf: "etfs", index: "indices", commodity: "commodities",
    fx: "fx", bond: "bonds" } as Record<string, string>)[assetClass] ?? assetClass;
}

export function isTabSlug(value: string): value is TabSlug {
  return TABS.some((t) => t.slug === value);
}

// Columns of the ranking table (chapter 2). `term` links to a glossary entry for the tooltip.
export const RANKING_COLUMNS: { key: string; label: string; term?: string; numeric?: boolean }[] = [
  { key: "rank", label: "Rang", term: "rangnummer", numeric: true },
  { key: "name", label: "Naam" },
  { key: "ticker", label: "Ticker" },
  { key: "grade", label: "Grade", term: "grade" },
  { key: "score", label: "Score", term: "score", numeric: true },
  { key: "quality", label: "Kwaliteit", term: "kwaliteit", numeric: true },
  { key: "timing", label: "Timing", term: "timing", numeric: true },
  { key: "change", label: "Δ maand", numeric: true },
  { key: "coverage", label: "Datadekking", term: "datadekking", numeric: true },
  { key: "price", label: "Koers (€)", term: "eur_koers", numeric: true },
  { key: "spark", label: "90 dagen" },
  { key: "plus", label: "Sterkste pluspunt" },
  { key: "minus", label: "Zwaarste minpunt" },
];
