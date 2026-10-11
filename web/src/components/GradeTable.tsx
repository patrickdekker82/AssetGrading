import { formatNumber } from "@/lib/format";
import { RANKING_COLUMNS } from "@/lib/tabs";
import { type GradeRow, GradeBadge } from "./GradeBadge";
import { Term } from "./Term";

const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumSignificantDigits: 6 });

function n(value: number | null): string {
  return value === null ? "–" : formatNumber(Math.round(value));
}

export function GradeTable({ rows }: { rows: GradeRow[] }) {
  return (
    <div className="table-wrap">
      <table className="ranking">
        <thead>
          <tr>
            {RANKING_COLUMNS.map((col) => (
              <th key={col.key} className={col.numeric ? "num" : undefined} scope="col">
                {col.term ? <Term id={col.term}>{col.label}</Term> : col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const none = r.status === "no_grade";
            return (
            <tr key={r.id} className={none ? "row-muted" : undefined}>
              <td className="num">{r.rank}</td>
              <td>
                <div className="name-cell">
                  <span>{r.name}</span>
                  <span className="muted small">{r.template}</span>
                </div>
              </td>
              <td>{r.ticker}</td>
              <td><GradeBadge row={r} /></td>
              <td className="num">{none ? "–" : n(r.score)}</td>
              <td className="num">{none ? "–" : n(r.quality)}</td>
              <td className="num">{n(r.timing)}</td>
              <td className="num">{r.letter_month_ago && r.letter ? (r.letter_month_ago === r.letter ? "=" : `${r.letter_month_ago} → ${r.letter}`) : "–"}</td>
              <td className="num">{Math.floor(r.coverage * 100)}%</td>
              <td className="num">{r.price_eur === null ? "–" : euro.format(r.price_eur)}</td>
              <td className="muted">–</td>
              <td className="small">
                {none ? <span className="muted" title={r.reason ?? undefined}>Geen grade: te weinig data</span> : r.plus ?? "–"}
              </td>
              <td className="small">{none ? "" : r.minus ?? "–"}</td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
