"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { formatNumber } from "@/lib/format";
import { applyFilters, EMPTY_FILTERS, type Filters, GRADE_ORDER, type SortKey, sortRows } from "@/lib/ranking";
import { RANKING_COLUMNS, tabForClass } from "@/lib/tabs";
import { type GradeRow, GradeBadge } from "./GradeBadge";
import { Sparkline } from "./Sparkline";
import { Term } from "./Term";

// What the "sector" field means per tab.
const GROUP_LABEL: Record<string, [string, string]> = {
  etfs: ["Filter index", "Alle indices"],
  bonds: ["Filter categorie", "Alle categorieën"],
  indices: ["Filter regio", "Alle regio's"],
};

const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumSignificantDigits: 6 });
const NUMERIC_FILTERS = new Set(["score", "quality", "timing", "coverage", "price"]);
const TEXT_FILTERS = new Set(["name", "ticker", "plus", "minus"]);

type View = { id: string; label: string; rows: GradeRow[] };

function n(value: number | null): string {
  return value === null ? "–" : formatNumber(Math.round(value));
}

export function RankingTable({ tab, views }: { tab: string; views: View[] }) {
  const [viewId, setViewId] = useState(views[0]?.id ?? "");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "rank", dir: 1 });
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const view = views.find((v) => v.id === viewId) ?? views[0];
  const templates = useMemo(() => [...new Set(view.rows.map((r) => r.template))].sort(), [view]);
  const sectors = useMemo(() => [...new Set(view.rows.map((r) => r.sector).filter(Boolean) as string[])].sort(), [view]);
  const countries = useMemo(() => [...new Set(view.rows.map((r) => r.country).filter(Boolean) as string[])].sort(),
    [view]);
  const ranked = useMemo(() => view.rows.map((r, i) => ({ ...r, rank: i + 1 })), [view]);
  const shown = useMemo(() => sortRows(applyFilters(ranked, filters), sort.key, sort.dir), [ranked, filters, sort]);
  const active = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS);

  function toggleSort(key: SortKey) {
    const textual = key === "name" || key === "ticker" || key === "plus" || key === "minus" || key === "rank";
    setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: textual ? 1 : -1 }));
  }

  function setText(key: string, value: string) {
    setFilters((f) => ({ ...f, text: { ...f.text, [key]: value } }));
  }

  function setMin(key: string, value: string) {
    setFilters((f) => ({ ...f, min: { ...f.min, [key]: value === "" ? undefined : Number(value) } }));
  }

  return (
    <div className="card">
      <div className="toolbar">
        {views.length > 1 && (
          <div className="segmented" role="tablist">
            {views.map((v) => (
              <button key={v.id} role="tab" aria-selected={v.id === view.id}
                className={v.id === view.id ? "seg active" : "seg"} onClick={() => setViewId(v.id)}>
                {v.label} <span className="muted">{v.rows.length}</span>
              </button>
            ))}
          </div>
        )}
        {sectors.length > 1 && (
          <select className="filter" aria-label={GROUP_LABEL[tab]?.[0] ?? "Filter sector"} value={filters.sector}
            onChange={(e) => setFilters((f) => ({ ...f, sector: e.target.value }))}>
            <option value="">{GROUP_LABEL[tab]?.[1] ?? "Alle sectoren"}</option>
            {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {countries.length > 1 && (
          <select className="filter" aria-label="Filter land" value={filters.country}
            onChange={(e) => setFilters((f) => ({ ...f, country: e.target.value }))}>
            <option value="">Alle landen</option>
            {countries.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        )}
        <label className="check">
          <input type="checkbox" checked={filters.changed}
            onChange={(e) => setFilters((f) => ({ ...f, changed: e.target.checked }))} />
          Grade gewijzigd
        </label>
        <label className="check">
          <input type="checkbox" checked={filters.falling}
            onChange={(e) => setFilters((f) => ({ ...f, falling: e.target.checked }))} />
          Gedaald in 90 dagen
        </label>
        <span className="muted small">{shown.length} van {view.rows.length}</span>
        {active && <button className="button" onClick={() => setFilters(EMPTY_FILTERS)}>Filters wissen</button>}
      </div>
      <div className="table-wrap">
        <table className="ranking">
          <thead>
            <tr>
              {RANKING_COLUMNS.map((col) => {
                const key = col.key as SortKey;
                const current = sort.key === key;
                return (
                  <th key={col.key} className={col.numeric ? "num" : undefined} scope="col"
                    aria-sort={current ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                    <button className="sort" onClick={() => toggleSort(key)}>
                      {col.term ? <Term id={col.term}>{col.label}</Term> : col.label}
                      <span className="sort-mark" aria-hidden="true">{current ? (sort.dir === 1 ? "▲" : "▼") : ""}</span>
                    </button>
                  </th>
                );
              })}
            </tr>
            <tr className="filter-row">
              {RANKING_COLUMNS.map((col) => (
                <th key={col.key} className={col.numeric ? "num" : undefined}>
                  {TEXT_FILTERS.has(col.key) && (
                    <input className="filter" placeholder="zoek" aria-label={`Filter ${col.label}`}
                      value={filters.text[col.key as keyof Filters["text"]] ?? ""}
                      onChange={(e) => setText(col.key, e.target.value)} />
                  )}
                  {NUMERIC_FILTERS.has(col.key) && (
                    <input className="filter num" type="number" placeholder="min" aria-label={`Minimum ${col.label}`}
                      value={filters.min[col.key as keyof Filters["min"]] ?? ""}
                      onChange={(e) => setMin(col.key, e.target.value)} />
                  )}
                  {col.key === "grade" && (
                    <select className="filter" aria-label="Filter grade" value={filters.grade}
                      onChange={(e) => setFilters((f) => ({ ...f, grade: e.target.value }))}>
                      <option value="">alle</option>
                      <option value="graded">met grade</option>
                      {GRADE_ORDER.slice(0, -1).map((g) => <option key={g} value={g}>{g} of beter</option>)}
                    </select>
                  )}
                  {col.key === "rank" && templates.length > 1 && (
                    <select className="filter" aria-label="Filter sjabloon" value={filters.template}
                      onChange={(e) => setFilters((f) => ({ ...f, template: e.target.value }))}>
                      <option value="">sjabloon</option>
                      {templates.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={RANKING_COLUMNS.length} className="muted center">Geen assets voor deze filters.</td></tr>
            )}
            {shown.map((r) => {
              const none = r.status === "no_grade";
              const href = `/${tab === "watchlist" ? tabForClass(r.asset_class) : tab}/${r.id}`;
              return (
                <tr key={r.id} className={none ? "row-muted" : undefined}>
                  <td className="num">{r.rank}</td>
                  <td>
                    <Link href={href} className="name-cell row-link">
                      <span>{r.name}</span>
                      <span className="muted small">
                        {r.product ? "Productoordeel" : r.template}{r.sector ? ` · ${r.sector}` : ""}
                        {r.country ? ` · ${r.country}` : ""}
                      </span>
                      {r.asset_class === "commodity" && (
                        <span className="muted small">
                          Product: {r.best_product ? `${r.best_product.name} (${r.best_product.letter ?? "–"})` : "geen gevolgd"}
                        </span>
                      )}
                    </Link>
                  </td>
                  <td>{r.ticker}</td>
                  <td><GradeBadge row={r} /></td>
                  <td className="num">{none ? "–" : n(r.score)}</td>
                  <td className="num">{none ? "–" : n(r.quality)}</td>
                  <td className="num">{n(r.timing)}</td>
                  <td className="num">
                    {r.letter_month_ago && r.letter ? (r.letter_month_ago === r.letter ? "=" : `${r.letter_month_ago} → ${r.letter}`) : "–"}
                  </td>
                  <td className="num">{Math.floor(r.coverage * 100)}%</td>
                  <td className="num">{r.price_eur === null ? "–" : euro.format(r.price_eur)}</td>
                  <td><Sparkline values={r.spark} /></td>
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
    </div>
  );
}
