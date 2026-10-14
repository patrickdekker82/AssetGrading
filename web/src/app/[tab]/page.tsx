import type { Metadata } from "next";
import { notFound } from "next/navigation";
import type { GradeRow } from "@/components/GradeBadge";
import { RankingTable as RankingTableLive } from "@/components/RankingTable";
import { Term } from "@/components/Term";
import { fetchServer } from "@/lib/server";
import { isTabSlug, RANKING_COLUMNS, TABS } from "@/lib/tabs";

type TabInfo = {
  slug: string;
  label_nl: string;
  phase: number;
  size: number | null;
  source: string;
  description_nl: string;
  template_names: string[];
};

type Props = { params: Promise<{ tab: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { tab } = await params;
  const label = TABS.find((t) => t.slug === tab)?.label;
  return { title: label ? `${label} · Graadmeter` : "Graadmeter" };
}

export default async function TabPage({ params }: Props) {
  const { tab } = await params;
  if (!isTabSlug(tab)) notFound();
  const label = TABS.find((t) => t.slug === tab)!.label;
  const tabs = await fetchServer<TabInfo[]>("/api/tabs");
  const info = tabs?.find((t) => t.slug === tab);

  return (
    <section>
      <div className="page-head">
        <h1>{label}</h1>
        {info?.size ? <span className="chip">Top {info.size}</span> : null}
      </div>
      {info ? <p className="lead">{info.description_nl}</p> : <ServerDown />}

      {info && info.template_names.length > 0 && (
        <p className="muted">
          <Term id="sjabloon">Sjablonen</Term>: {info.template_names.join(" · ")}
        </p>
      )}

      {tab === "indices" && <RegimeCard />}
      {tab === "bonds" && <RatesCard />}
      {tab === "model" ? (
        <EmptyState phase={info?.phase ?? 8}
          text="Hier verschijnt de staat van dienst van het model: rendement per letter tegen de benchmark, de rangcorrelatie per maand en openstaande voorstellen. Live resultaten en terugtest staan altijd gescheiden." />
      ) : (
        <Ranking tab={tab} phase={info?.phase ?? 1} />
      )}
    </section>
  );
}

type Grades = { as_of: string | null; model_version: string; rows: GradeRow[] };

async function Ranking({ tab, phase }: { tab: string; phase: number }) {
  const grades = await fetchServer<Grades>(`/api/grades?tab=${tab}`);
  if (!grades || !grades.as_of || grades.rows.length === 0) {
    return tab === "watchlist"
      ? <EmptyState phase={phase} text="Je volglijst is nog leeg. Zoek een asset en kies 'Volgen'." />
      : <RankingTable phase={phase} />;
  }
  const list = tab === "watchlist" ? grades.rows : grades.rows.filter((r) => r.in_list);
  const stable = grades.rows.filter((r) => r.exclusion === "stablecoin");
  const withGrade = list.filter((r) => r.status !== "no_grade").length;
  const us = grades.rows.filter((r) => r.lists?.includes("VS"));
  const aex = grades.rows.filter((r) => r.lists?.includes("AEX"));
  const views = tab === "watchlist"
    ? [{ id: "all", label: "Volglijst", rows: list }]
    : ["etfs", "bonds", "indices"].includes(tab)
      ? [{ id: "list", label: "Alle", rows: list }]
      : tab === "stocks"
      ? [
        { id: "list", label: "VS en AEX", rows: list },
        { id: "us", label: `VS top ${us.length}`, rows: us },
        { id: "aex", label: "AEX", rows: aex },
        { id: "all", label: "Alle gevolgde", rows: grades.rows },
      ]
      : [
        { id: "list", label: `Top ${list.length}`, rows: list },
        ...(stable.length ? [{ id: "stable", label: "Stablecoins", rows: stable }] : []),
        { id: "all", label: "Alle gevolgde", rows: grades.rows },
      ];
  return (
    <>
      <p className="meta">
        <Term id="peildatum">Peildatum</Term> {grades.as_of} · <Term id="modelversie">Modelversie</Term>{" "}
        {grades.model_version} · <Term id="horizon">Horizon</Term> 6–12 maanden · {withGrade} van {list.length} met grade
      </p>
      <RankingTableLive tab={tab} views={views} />
    </>
  );
}

function RankingTable({ phase }: { phase: number }) {
  return (
    <div className="card">
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
      </table>
      </div>
      <p className="empty-row">Nog geen data. Deze ranglijst wordt gevuld vanaf fase {phase}.</p>
    </div>
  );
}

function EmptyState({ phase, text }: { phase: number; text: string }) {
  return (
    <div className="empty">
      <p>{text}</p>
      <p className="muted">Beschikbaar vanaf fase {phase}.</p>
    </div>
  );
}

function ServerDown() {
  return (
    <p className="notice">
      De rekenserver is niet bereikbaar. Controleer of alle containers draaien (zie README).
    </p>
  );
}

type RegimeInput = { value: number; date: string; vote: number; percentile?: number; average_10m?: number;
  history_from?: string } | null;
type Regime = {
  latest: null | { date: string; state: string | null; score: number | null; week_end: string;
    inputs: { world_index: RegimeInput; high_yield_spread: RegimeInput; vix: RegimeInput } };
  history: { week_end: string; state: string | null }[];
};
const REGIME_NL: Record<string, string> = { risk_on: "Risico aan", neutral: "Neutraal", risk_off: "Risico uit" };
const VOTE: Record<number, string> = { 1: "rustig (+1)", 0: "neutraal (0)", [-1]: "onrustig (−1)" };
const nl = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 });

async function RegimeCard() {
  const r = await fetchServer<Regime>("/api/regime?days=400");
  if (!r?.latest) return null;
  const { inputs, state, week_end: weekEnd } = r.latest;
  const recent = r.history.slice(-52);
  return (
    <div className="card regime-card">
      <h2 className="card-title"><Term id="marktregime">Marktregime</Term>:{" "}
        <span className={`regime regime-${state ?? "none"}`}>{state ? REGIME_NL[state] : "onbekend"}</span></h2>
      <p className="muted small">Bepaald op de afgesloten week tot en met {weekEnd}. Geldt voor de grades van aandelen
        en crypto: bij risico uit gaat de grade één stapje omlaag; gates blijven altijd gelden.</p>
      <ul className="regime-inputs small">
        <li>Wereldindex (MSCI World): {inputs.world_index
          ? <>{nl.format(inputs.world_index.value)} tegen 10-maandsgemiddelde {nl.format(inputs.world_index.average_10m ?? 0)}
            {" "}→ {VOTE[inputs.world_index.vote]}</> : "geen data"}</li>
        <li>Renteopslag high yield (FRED): {inputs.high_yield_spread
          ? <>{nl.format(inputs.high_yield_spread.value)}%, percentiel {nl.format(inputs.high_yield_spread.percentile ?? 0)} sinds
            {" "}{inputs.high_yield_spread.history_from} → {VOTE[inputs.high_yield_spread.vote]}</> : "geen data"}</li>
        <li>VIX: {inputs.vix
          ? <>{nl.format(inputs.vix.value)}, percentiel {nl.format(inputs.vix.percentile ?? 0)} over tien jaar
            {" "}→ {VOTE[inputs.vix.vote]}</> : "geen data"}</li>
      </ul>
      <div className="regime-strip" aria-label="Regime per week, laatste jaar">
        {recent.map((w) => (
          <span key={w.week_end} className={`regime-cell regime-${w.state ?? "none"}`}
            title={`${w.week_end}: ${w.state ? REGIME_NL[w.state] : "onbekend"}`} />
        ))}
      </div>
      <p className="muted small">Per week, het laatste jaar (oud links, nieuw rechts).</p>
    </div>
  );
}

type Rate = { series: string; name: string; date: string; value: number; year_ago: number | null };

async function RatesCard() {
  const rates = await fetchServer<Rate[]>("/api/rates");
  if (!rates?.length) return null;
  return (
    <div className="card">
      <h2 className="card-title">Staatsrentes ter vergelijking</h2>
      <div className="table-wrap">
        <table className="ranking">
          <thead><tr><th>Rente</th><th className="num">Nu</th><th className="num">Een jaar geleden</th><th>Datum</th></tr></thead>
          <tbody>
            {rates.map((r) => (
              <tr key={r.series}>
                <td>{r.name}</td><td className="num">{nl.format(r.value)}%</td>
                <td className="num">{r.year_ago === null ? "–" : `${nl.format(r.year_ago)}%`}</td>
                <td className="muted small">{r.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Bron: FRED (VS) en ECB (eurozone, AAA-staatsobligaties). Een rente is geen product en krijgt geen grade.</p>
    </div>
  );
}
