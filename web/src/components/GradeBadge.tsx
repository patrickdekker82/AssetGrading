import { Term } from "./Term";

export type GradeRow = {
  id: string;
  rank: number;
  name: string;
  ticker: string;
  template: string;
  status: "graded" | "provisional" | "speculative" | "peg_safety" | "no_grade";
  letter: string | null;
  letter_low: string | null;
  letter_high: string | null;
  score: number | null;
  quality: number | null;
  timing: number | null;
  coverage: number;
  peg_safety: number | null;
  price_eur: number | null;
  labels: string[];
  reason: string | null;
  plus: string | null;
  minus: string | null;
  letter_month_ago: string | null;
  in_list: boolean;
  exclusion: string | null;
  mcap_rank: number | null;
  btc_relative: string | null;
  spark: number[];
  watched: boolean;
  asset_class: string;
  sector?: string | null;
  country?: string | null;
  market_cap_eur?: number | null;
  lists?: string[];
  direction?: string | null;
  product?: boolean;
  best_product?: { id: string; name: string; letter: string | null; score: number | null; coverage?: number | null } | null;
};

function tone(letter: string): string {
  return `grade grade-${letter[0].toLowerCase()}`;
}

export function GradeBadge({ row }: { row: GradeRow }) {
  if (row.status === "no_grade" || (!row.letter && row.peg_safety === null)) {
    return <span className="grade grade-none" title={row.reason ?? undefined}>–</span>;
  }
  if (row.status === "peg_safety") {
    return (
      <span className={`grade peg peg-${row.peg_safety}`} title="Pegveiligheid: 1 sterk, 5 zwak">
        <Term id="pegveiligheid">Peg {row.peg_safety}</Term>
      </span>
    );
  }
  const range = row.letter_low && row.letter_high && row.letter_low !== row.letter_high
    ? `${row.letter} (${row.letter_low} tot ${row.letter_high})` : row.letter!;
  const provisional = row.status === "provisional";
  return (
    <span className="grade-cell">
      <span className={provisional ? "grade grade-provisional" : tone(row.letter!)} title={range}>{row.letter}</span>
      {provisional && <span className="tag"><Term id="voorlopig">voorlopig</Term></span>}
      {row.labels.includes("speculatie") && <span className="tag"><Term id="speculatie">speculatie</Term></span>}
    </span>
  );
}
