import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { HistoryChart, type HistoryPoint } from "@/components/chart/HistoryChart";
import { PriceChart } from "@/components/chart/PriceChart";
import { Term } from "@/components/Term";
import { WatchButton } from "@/components/WatchButton";
import { directionText, formatMetric, groupName } from "@/lib/metrics";
import { fetchServer } from "@/lib/server";
import { isTabSlug, TABS } from "@/lib/tabs";

type Metric = { id: string; value: number | null; score: number | null; weight: number; used_as_fallback: boolean;
  unit: string | null; direction: string | null; peer_pct: number | null; own_pct: number | null;
  source: string | null; peer_group: string | null; peer_count: number | null };
type Pillar = { id: string; name_nl: string; weight: number; effective_weight: number; score: number | null;
  coverage: number; timing: boolean; contribution: number | null; metrics: Metric[];
  horizon_months?: number[] | null };
type Gate = { id: string; status: string; cap: string | null; label_nl: string | null; reason_nl: string;
  detail: string | null };
type Detail = {
  asset: { id: string; name: string; ticker: string; asset_class: string; template?: string; template_name?: string;
    categories: string[]; in_watchlist: boolean; price_sources: string[]; sector: string | null;
    country: string | null };
  price: { ts: string; source: string; quote_currency: string; close_native: number; close_eur: number } | null;
  history: HistoryPoint[];
  snapshot: null | { as_of: string; model_version: string; status: string; letter: string | null;
    letter_low: string | null; letter_high: string | null; score: number | null; quality: number | null;
    timing: number | null; coverage: number; peg_safety: number | null; labels: string[]; reason: string | null;
    horizon_months: number[]; notes: string[]; btc_relative: { score: number; letter: string } | null;
    data_notes: string[] };
  pillars?: Pillar[];
  gates?: Gate[];
  explanation?: string;
  explanation_source?: "taalmodel" | "sjabloon";
  explanation_meta?: { written_for: string; used_metrics: string[]; rejected?: boolean };
};

type Props = { params: Promise<{ tab: string; asset: string }> };

const euro = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR", maximumSignificantDigits: 6 });
const native = new Intl.NumberFormat("nl-NL", { maximumSignificantDigits: 6 });
const GATE_STATUS: Record<string, string> = { hit: "Geraakt", clear: "In orde", unknown: "Niet te controleren" };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { asset } = await params;
  const d = await fetchServer<Detail>(`/api/assets/${encodeURIComponent(asset)}`);
  return { title: d ? `${d.asset.name} · Graadmeter` : "Graadmeter" };
}

function horizon(months: number[]): string {
  if (months.length === 1) return months[0] >= 12 ? `${months[0] / 12} jaar` : `${months[0]} maanden`;
  return `${months[0]}–${months[months.length - 1]} maanden`;
}

function n(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : Math.round(v).toString();
}

export default async function AssetPage({ params }: Props) {
  const { tab, asset } = await params;
  if (!isTabSlug(tab)) notFound();
  const d = await fetchServer<Detail>(`/api/assets/${encodeURIComponent(asset)}`);
  if (!d) notFound();
  const s = d.snapshot;
  const tabLabel = TABS.find((t) => t.slug === tab)?.label ?? tab;

  return (
    <article className="stack asset-page">
      <nav className="crumbs small"><Link href={`/${tab}`}>{tabLabel}</Link> / {d.asset.name}</nav>

      {/* 1. Kop */}
      <header className="card asset-head">
        <div className="asset-title">
          <div>
            <h1>{d.asset.name} <span className="muted">{d.asset.ticker}</span></h1>
            <p className="muted small">
              {d.asset.template_name ? <><Term id="sjabloon">Sjabloon</Term>: {d.asset.template_name}</> : null}
              {d.asset.sector && (d.asset.asset_class === "stock"
                ? <> · <Term id="sector">Sector</Term>: {d.asset.sector}</>
                : <> · {({ etf: "Index", bond: "Categorie", index: "Regio" } as Record<string, string>)[d.asset.asset_class] ?? "Groep"}: {d.asset.sector}</>)}
              {d.asset.country && <> · {d.asset.country}</>}
              {d.price && <> · {euro.format(d.price.close_eur)}
                {d.price.quote_currency !== "EUR" && <> ({native.format(d.price.close_native)} {d.price.quote_currency})</>}
                {" "}slot {d.price.ts}</>}
            </p>
          </div>
          <WatchButton id={d.asset.id} initial={d.asset.in_watchlist} />
        </div>
        {s ? (
          <div className="head-grid">
            <HeadStat label={<Term id="grade">Grade</Term>} value={<GradeValue s={s} />}
              hint={s.letter_low && s.letter_high && s.letter_low !== s.letter_high ? `bandbreedte ${s.letter_low} tot ${s.letter_high}` : s.labels.join(", ")} />
            <HeadStat label={<Term id="score">Score</Term>} value={n(s.score)} hint="van 100" />
            <HeadStat label={<Term id="kwaliteit">Kwaliteit</Term>} value={n(s.quality)} hint="zonder trend en momentum" />
            <HeadStat label={<Term id="timing">Timing</Term>} value={n(s.timing)} hint="technische score" />
            <HeadStat label={<Term id="datadekking">Datadekking</Term>} value={`${Math.floor(s.coverage * 100)}%`}
              hint={s.coverage < 0.6 ? "onder 60%: voorlopig" : "gevuld met echte data"} />
            <HeadStat label={<Term id="modelversie">Modelversie</Term>} value={s.model_version}
              hint={<><Term id="peildatum">peildatum</Term> {s.as_of} · <Term id="horizon">horizon</Term> {horizon(s.horizon_months)}</>} />
            {s.btc_relative && (
              <HeadStat label="Grade t.o.v. Bitcoin" value={s.btc_relative.letter} hint="technische score in BTC gemeten" />
            )}
          </div>
        ) : (
          <p className="notice">Voor deze asset is nog geen grade berekend. Dat gebeurt in de eerstvolgende nachtrun.</p>
        )}
        {s?.reason && <p className="notice">{s.reason}</p>}
        {s && s.data_notes.length > 0 && (
          <p className="muted small">Bij de data: {s.data_notes.join(" · ")}</p>
        )}
      </header>

      {["etf", "bond", "etc"].includes(d.asset.asset_class) && <Characteristics categories={d.asset.categories} />}
      {d.asset.asset_class === "etf" && <EtfPeers id={d.asset.id} />}
      {["commodity", "etc", "fx"].includes(d.asset.asset_class) && <Related id={d.asset.id} kind={d.asset.asset_class} score={s?.score ?? null} />}

      {s && d.pillars && d.pillars.length > 0 && (
        <>
          {/* 2. Pijlers */}
          <section className="card">
            <h2 className="card-title"><Term id="pijler">Pijlers</Term></h2>
            <div className="pillars">
              {d.pillars.map((p) => (
                <div key={p.id} className="pillar-row">
                  <div className="pillar-name">{p.name_nl}{p.timing && <span className="tag">timing</span>}
                    {p.horizon_months && <span className="tag" title="Horizon van deze pijler">{horizon(p.horizon_months)}</span>}</div>
                  <div className="bar" role="img" aria-label={`${p.name_nl}: ${n(p.score)} van 100`}>
                    <span style={{ width: `${p.score ?? 0}%` }} className={p.score === null ? "" : p.score >= 60 ? "good" : p.score < 40 ? "bad" : "mid"} />
                  </div>
                  <div className="num">{n(p.score)}</div>
                  <div className="num muted small" title="Gewicht na herverdeling (instelling)">
                    {Math.round(p.effective_weight)}% <span className="muted">({p.weight})</span>
                  </div>
                  <div className="num small">{p.contribution === null ? "–" : `+${p.contribution.toFixed(1)}`}</div>
                </div>
              ))}
              <div className="pillar-row pillar-legend muted small">
                <div /><div>score 0–100</div><div /><div className="num"><Term id="gewicht">gewicht</Term></div>
                <div className="num">bijdrage</div>
              </div>
            </div>
          </section>

          {/* 3. Onderbouwing per maatstaf */}
          <section className="card">
            <h2 className="card-title">Onderbouwing per <Term id="maatstaf">maatstaf</Term></h2>
            {d.pillars.map((p) => (
              <details key={p.id} className="details" open={p.metrics.some((m) => m.score !== null)}>
                <summary>{p.name_nl} <span className="muted small">· {Math.round(p.coverage * 100)}% gevuld</span></summary>
                <div className="table-wrap">
                  <table className="ranking metrics">
                    <thead>
                      <tr>
                        <th scope="col">Maatstaf</th><th scope="col" className="num">Waarde</th>
                        <th scope="col" className="num">Score</th><th scope="col">Positie</th>
                        <th scope="col">Richting</th><th scope="col">Bron en datum</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.metrics.map((m) => (
                        <tr key={m.id} className={m.score === null ? "row-muted" : undefined}>
                          <td><Term id={m.id} />{m.used_as_fallback && <span className="tag">terugval</span>}</td>
                          <td className="num">{formatMetric(m.value, m.unit)}</td>
                          <td className="num">{m.score === null ? "–" : Math.round(m.score)}</td>
                          <td className="small">
                            {m.peer_pct === null ? (m.score === null ? "geen data" : "directe score")
                              : <><Term id="percentiel">percentiel</Term> {Math.round(m.peer_pct)} in {groupName(m.peer_group)}
                                {m.peer_count ? ` (${m.peer_count})` : ""}
                                {m.own_pct !== null && <>; eigen historie {Math.round(m.own_pct)}</>}</>}
                          </td>
                          <td className="small muted">{directionText(m.direction)}</td>
                          <td className="small muted">{m.source ?? "–"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ))}
          </section>
        </>
      )}

      {/* 4. Gates */}
      {s && d.gates && d.gates.length > 0 && (
        <section className="card">
          <h2 className="card-title"><Term id="gate">Gates</Term></h2>
          <ul className="gate-list">
            {d.gates.map((g) => (
              <li key={g.id} className={`gate gate-${g.status}`}>
                <span className="gate-status">{GATE_STATUS[g.status] ?? g.status}</span>
                <span>{g.reason_nl}{g.cap && <> Begrenzing: hoogstens <strong>{g.cap}</strong>.</>}</span>
                {g.detail && <span className="muted small"> ({g.detail})</span>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 5. Toelichting */}
      {d.explanation && (
        <section className="card prose">
          <h2 className="card-title">Toelichting</h2>
          <p>{d.explanation}</p>
          <p className="muted small">{explanationNote(d)}</p>
        </section>
      )}

      {/* 6. Grafiek */}
      <section className="card">
        <h2 className="card-title">Grafiek</h2>
        <PriceChart assetId={d.asset.id} />
      </section>

      {/* 7. Geschiedenis */}
      <section className="card">
        <h2 className="card-title">Geschiedenis van score en grade</h2>
        <div className="card-body"><HistoryChart points={d.history} /></div>
      </section>
    </article>
  );
}

function HeadStat({ label, value, hint }: { label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint muted">{hint}</div>}
    </div>
  );
}

function GradeValue({ s }: { s: NonNullable<Detail["snapshot"]> }) {
  if (s.status === "peg_safety") return <span className="grade peg big">Peg {s.peg_safety}</span>;
  if (!s.letter) return <span className="muted">geen</span>;
  const cls = s.status === "provisional" ? "grade grade-provisional big" : `grade grade-${s.letter[0].toLowerCase()} big`;
  return <span className={cls}>{s.letter}</span>;
}

const CHARACTERISTIC_LABELS: Record<string, string> = {
  issuer: "Uitgever", domicile: "Domicilie", replication: "Replicatie", distribution: "Dividend",
  securities_lending: "Uitlenen van effecten", launch_date: "Start", category: "Categorie",
  currency_hedged: "Valutarisico afgedekt", fund_currency: "Fondsvaluta", leveraged_inverse: "Hefboom of invers",
  structure: "Structuur", collateralized: "Onderpand", trading_currency: "Handelsvaluta",
};
const VALUE_LABELS: Record<string, string> = {
  full: "volledig fysiek", sampling: "fysiek, steekproef", synthetic: "synthetisch (swap)", acc: "herbeleggend",
  dist: "uitkerend", yes: "ja", no: "nee", physical: "fysiek (metaal in een kluis)",
  futures: "termijncontracten", swap: "swap",
};

function Characteristics({ categories }: { categories: string[] }) {
  const rows = categories.map((c) => c.split(":")).filter(([k]) => k in CHARACTERISTIC_LABELS);
  if (!rows.length) return null;
  return (
    <section className="card">
      <h2 className="card-title">Kenmerken</h2>
      <dl className="facts small">
        {rows.map(([k, ...v]) => (
          <div key={k}><dt className="muted">{CHARACTERISTIC_LABELS[k]}</dt><dd>{VALUE_LABELS[v.join(":")] ?? v.join(":")}</dd></div>
        ))}
      </dl>
      <p className="muted small">Uit het zelf bijgehouden bestand met bron en datum per fonds (config/etfs.csv of bond_etfs.csv).</p>
    </section>
  );
}

type PeerRow = { id: string; name: string; letter: string | null; status: string; score: number | null;
  tracking_difference: number | null; ongoing_charges: number | null; rest_after_costs: number | null;
  fund_size: number | null; domicile: string | null; replication: string | null; distribution: string | null;
  securities_lending: string | null; td_source: string | null };
const pct = new Intl.NumberFormat("nl-NL", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const mln = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 0 });

async function EtfPeers({ id }: { id: string }) {
  const p = await fetchServer<{ group: string | null; rows: PeerRow[] }>(`/api/assets/${encodeURIComponent(id)}/peers`);
  if (!p?.group || p.rows.length < 2) return null;
  const source = p.rows.find((r) => r.td_source)?.td_source;
  return (
    <section className="card">
      <h2 className="card-title">ETF&apos;s op dezelfde index: {p.group}</h2>
      <div className="table-wrap">
        <table className="ranking">
          <thead>
            <tr>
              <th>Fonds</th><th>Grade</th>
              <th className="num"><Term id="tracking_difference">Tracking difference</Term></th>
              <th className="num"><Term id="ongoing_charges">Kosten</Term></th>
              <th className="num"><Term id="rest_na_kosten">Rest na kosten</Term></th>
              <th>Domicilie</th><th>Replicatie</th><th>Uitlenen</th><th className="num">Omvang (mln €)</th>
            </tr>
          </thead>
          <tbody>
            {p.rows.map((r) => (
              <tr key={r.id} className={r.id === id ? "row-current" : undefined}>
                <td><Link href={`/etfs/${r.id}`}>{r.name}</Link></td>
                <td>{r.status === "no_grade" ? "–" : r.letter}</td>
                <td className="num">{r.tracking_difference === null ? "–" : pct.format(r.tracking_difference)}</td>
                <td className="num">{r.ongoing_charges === null ? "–" : pct.format(r.ongoing_charges)}</td>
                <td className="num">{r.rest_after_costs === null ? "–" : pct.format(r.rest_after_costs)}</td>
                <td>{r.domicile ?? "–"}</td>
                <td>{r.replication ? VALUE_LABELS[r.replication] ?? r.replication : "–"}</td>
                <td>{r.securities_lending ? VALUE_LABELS[r.securities_lending] : "–"}</td>
                <td className="num">{r.fund_size === null ? "–" : mln.format(r.fund_size / 1e6)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Tracking difference per jaar = kosten + rest. De kosten verklaren het grootste deel; de rest komt van
        belasting op dividend (domicilie, of synthetisch zonder Amerikaanse bronbelasting), opbrengst uit het
        uitlenen van effecten en de manier van repliceren.{source ? ` Gemeten: ${source}.` : ""}
      </p>
    </section>
  );
}

type RelatedRow = { id: string; name: string; asset_class: string; letter: string | null; status: string;
  score: number | null; structure: string | null; collateralized: string | null; ongoing_charges: number | null;
  roll_yield_12m: number | null; tracking_difference: number | null };

async function Related({ id, kind, score }: { id: string; kind: string; score: number | null }) {
  const r = await fetchServer<{ rows: RelatedRow[] }>(`/api/assets/${encodeURIComponent(id)}/products`);
  if (!r) return null;
  if (kind === "fx") {
    const m = r.rows[0];
    if (!m) return null;
    return (
      <section className="card">
        <h2 className="card-title">Spiegelpaar</h2>
        <p><Link href={`/fx/${m.id}`}>{m.name}</Link>: {m.status === "no_grade" ? "geen grade" : `${m.letter}, score ${n(m.score)}`}.
          {score !== null && m.score !== null && <> Samen {n(score + m.score)}: een richtingsscore voor de ene kant is het
            spiegelbeeld van de andere.</>}</p>
      </section>
    );
  }
  if (kind === "etc") {
    const c = r.rows[0];
    if (!c) return null;
    return (
      <section className="card">
        <h2 className="card-title">Oordeel over de grondstof zelf</h2>
        <p><Link href={`/commodities/${c.id}`}>{c.name}</Link>: {c.status === "no_grade" ? "geen grade" : c.letter}.
          De grade hierboven is het productoordeel: hoe goed dit product de grondstof volgt en wat het kost.</p>
      </section>
    );
  }
  return (
    <section className="card">
      <h2 className="card-title">Producten om deze grondstof aan te houden</h2>
      {r.rows.length === 0 ? <p className="muted">Geen product (ETC) gevolgd voor deze grondstof.</p> : (
        <div className="table-wrap">
          <table className="ranking">
            <thead><tr><th>Product</th><th>Productoordeel</th><th>Structuur</th><th>Onderpand</th>
              <th className="num"><Term id="ongoing_charges">Kosten</Term></th>
              <th className="num"><Term id="roll_yield_12m">Rolopbrengst 12 mnd</Term></th></tr></thead>
            <tbody>
              {r.rows.map((p) => (
                <tr key={p.id}>
                  <td><Link href={`/commodities/${p.id}`}>{p.name}</Link></td>
                  <td>{p.status === "no_grade" ? "–" : p.letter}</td>
                  <td>{p.structure ? VALUE_LABELS[p.structure] ?? p.structure : "–"}</td>
                  <td>{p.collateralized ? VALUE_LABELS[p.collateralized] : "–"}</td>
                  <td className="num">{p.ongoing_charges === null ? "–" : pct.format(p.ongoing_charges)}</td>
                  <td className="num">{p.roll_yield_12m === null ? "–" : pct.format(p.roll_yield_12m)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">Een particulier kan de grondstof zelf niet aanhouden; daarom twee oordelen: de grondstof
        (hierboven) en het product. Rolopbrengst: rendement van het product min de koersverandering van het
        eerstvolgende termijncontract.</p>
    </section>
  );
}

function explanationNote(d: Detail): string {
  const meta = d.explanation_meta;
  if (d.explanation_source === "taalmodel" && meta) {
    return `Geschreven door een taalmodel bij de grade van ${meta.written_for}. Elk getal is gecontroleerd ` +
      "tegen de berekende cijfers; de grade zelf komt altijd uit het model.";
  }
  if (meta?.rejected) {
    return "Vaste sjabloontekst: de tekst van het taalmodel kwam niet door de getalcontrole.";
  }
  return "Vaste sjabloontekst op basis van de berekende cijfers.";
}
