import type { GradeRow } from "@/components/GradeBadge";

export const GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"];

export type SortKey = "rank" | "name" | "ticker" | "grade" | "score" | "quality" | "timing" | "change" | "coverage"
  | "price" | "spark" | "plus" | "minus";

/** Sort value per column; rows without a value always go last. */
export function sortValue(r: GradeRow, key: SortKey): number | string | null {
  switch (key) {
    case "rank": return r.rank;
    case "name": return r.name.toLowerCase();
    case "ticker": return r.ticker.toLowerCase();
    case "grade": return r.letter && r.status !== "no_grade" ? -GRADE_ORDER.indexOf(r.letter) : null;
    case "score": return r.status === "no_grade" ? null : r.score;
    case "quality": return r.status === "no_grade" ? null : r.quality;
    case "timing": return r.timing;
    case "change": return r.letter && r.letter_month_ago ? GRADE_ORDER.indexOf(r.letter_month_ago) - GRADE_ORDER.indexOf(r.letter) : null;
    case "coverage": return r.coverage;
    case "price": return r.price_eur;
    case "spark": return r.spark.length > 1 ? r.spark[r.spark.length - 1] / r.spark[0] - 1 : null;
    case "plus": return r.plus?.toLowerCase() ?? null;
    case "minus": return r.minus?.toLowerCase() ?? null;
  }
}

export function sortRows(rows: GradeRow[], key: SortKey, dir: 1 | -1): GradeRow[] {
  return [...rows].sort((a, b) => {
    const va = sortValue(a, key);
    const vb = sortValue(b, key);
    if (va === null && vb === null) return a.rank - b.rank;
    if (va === null) return 1;
    if (vb === null) return -1;
    if (va < vb) return -dir;
    if (va > vb) return dir;
    return a.rank - b.rank;
  });
}

export type Filters = {
  text: Partial<Record<"name" | "ticker" | "plus" | "minus", string>>;
  min: Partial<Record<"score" | "quality" | "timing" | "coverage" | "price", number>>;
  grade: string;          // "" = all, "graded" = only with a grade, otherwise "at least this letter"
  template: string;
  sector: string;
  country: string;
  changed: boolean;
  falling: boolean;
};

export const EMPTY_FILTERS: Filters = {
  text: {}, min: {}, grade: "", template: "", sector: "", country: "", changed: false, falling: false,
};

export function applyFilters(rows: GradeRow[], f: Filters): GradeRow[] {
  return rows.filter((r) => {
    for (const [key, needle] of Object.entries(f.text)) {
      if (!needle) continue;
      const hay = key === "name" ? `${r.name} ${r.template}` : ((r as Record<string, unknown>)[key] as string | null) ?? "";
      if (!hay.toLowerCase().includes(needle.toLowerCase())) return false;
    }
    for (const [key, min] of Object.entries(f.min)) {
      if (min === undefined || Number.isNaN(min)) continue;
      const value = key === "coverage" ? r.coverage * 100 : key === "price" ? r.price_eur
        : (r as Record<string, unknown>)[key] as number | null;
      if (value === null || value === undefined || value < min) return false;
    }
    if (f.grade === "graded" && (r.status === "no_grade" || !r.letter)) return false;
    if (f.grade && f.grade !== "graded") {
      if (!r.letter || r.status === "no_grade" || GRADE_ORDER.indexOf(r.letter) > GRADE_ORDER.indexOf(f.grade)) return false;
    }
    if (f.template && r.template !== f.template) return false;
    if (f.sector && r.sector !== f.sector) return false;
    if (f.country && r.country !== f.country) return false;
    if (f.changed && (!r.letter_month_ago || r.letter_month_ago === r.letter)) return false;
    if (f.falling && !(r.spark.length > 1 && r.spark[r.spark.length - 1] < r.spark[0])) return false;
    return true;
  });
}
