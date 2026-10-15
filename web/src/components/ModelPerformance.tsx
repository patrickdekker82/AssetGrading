import Link from "next/link";
import { LearningPanel } from "@/components/LearningPanel";
import { ProposalButtons } from "@/components/ProposalButtons";
import { Term } from "@/components/Term";
import { formatDateTime, formatNumber } from "@/lib/format";
import { fetchServer } from "@/lib/server";

// The Model page (chapter 8): the live track record first and on its own, the backtest below it and
// always labelled as recomputed history, then the open proposals.

type LetterStat = {
  n: number; months: number; mean_excess: number; median_excess: number; monthly_mean: number | null;
  ci95: [number, number] | null; share_beat_benchmark: number; worst_drawdown: number | null;
};
type Measure = {
  horizon_months: number;
  newey_west_lags: number;
  ic: { months: number; mean: number | null; share_positive: number | null; t_newey_west: number | null;
    by_month: Record<string, number> };
  letters: { per_letter: Record<string, LetterStat>; a_minus_f: { mean: number | null; t_newey_west: number | null } | null;
    order: { holds: boolean | null; inversions: number | null }; big_misses: number };
  turnover: { letter_changed: number | null };
};
type Coverage = { months: number; assets: number; assets_per_month: number | null; first: string | null; last: string | null };
type TemplateReport = { name_nl: string; tab: string; coverage: Coverage; horizons: Record<string, Measure> };
type Report = { label: string; computed_at: string; templates: Record<string, TemplateReport> };
type Performance = {
  model_version: string;
  live: { insufficient: boolean; months_with_outcomes: number; min_months: number; first_grade: string | null;
    report: Report | null };
  backtest: { label: string; computed_at: string | null; report: Report | null;
    run: { id: number; params: { start: string; end: string; months: number }; finished_at: string } | null;
    running: { id: number; started_at: string } | null };
};
type CalibrationEntry = { name_nl?: string; months: number; observations: number; current: Record<string, number>;
  proposed: Record<string, number> | null; reason_nl?: string;
  distribution_current?: Record<string, number>; distribution_proposed?: Record<string, number> };
type Proposal = { id: number; kind: string; status: string; created_at: string; decided_at: string | null;
  applied_version: string | null; run_id: number | null; summary_nl: string; source: string;
  refusal: string[] | null; payload: Record<string, unknown>; evidence: Record<string, unknown>;
  model_version: string | null; current: boolean };
type GateTest = { observations: number; misses: number;
  best: { percentile: number; threshold: number; misses_caught: number; false_alarms: number } | null };

export const HORIZONS = [1, 3, 6, 12];
const LETTERS = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D", "D-", "F"];
const pctFmt = new Intl.NumberFormat("nl-NL", { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" });
const shareFmt = new Intl.NumberFormat("nl-NL", { style: "percent", maximumFractionDigits: 1 });
const share = (v: number | null | undefined) => (v === null || v === undefined ? "–" : shareFmt.format(v));
const numFmt = new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 2 });
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : pctFmt.format(v));
const num = (v: number | null | undefined) => (v === null || v === undefined ? "–" : numFmt.format(v));
const STATUS_NL: Record<string, string> = { open: "open", approved: "goedgekeurd", rejected: "afgewezen",
  refused: "geweigerd door de vangrails" };
const SOURCE_NL: Record<string, string> = { model: "berekend", taalmodel: "taalmodel", owner: "eigenaar" };

export async function ModelPerformance({ horizon }: { horizon: number }) {
  const [perf, proposals] = await Promise.all([
    fetchServer<Performance>("/api/model/performance"),
    fetchServer<Proposal[]>("/api/model/proposals"),
  ]);
  if (!perf) return <p className="notice">De rekenserver is niet bereikbaar.</p>;
  const h = String(horizon);

  return (
    <div className="stack">
      <nav className="horizon-pick" aria-label="Horizon">
        <span className="muted"><Term id="horizon">Horizon</Term>:</span>
        {HORIZONS.map((m) => (
          <Link key={m} href={`/model?h=${m}`} className={m === horizon ? "button active" : "button"}>
            {m} {m === 1 ? "maand" : "maanden"}
          </Link>
        ))}
      </nav>

      <section className="card">
        <h2 className="card-title">Staat van dienst (live)</h2>
        <p className="card-foot">
          Alleen grades die de app op het moment zelf gaf, gemeten tegen wat daarna gebeurde. Modelversie{" "}
          {perf.model_version}; eerste live grade {perf.live.first_grade ?? "–"}.
        </p>
        {perf.live.insufficient && (
          <p className="notice">
            <strong>Onvoldoende data.</strong> {perf.live.months_with_outcomes} van de {perf.live.min_months} maanden
            met een uitkomst. Een uitkomst ontstaat pas als een maand is afgesloten en de horizon voorbij is; tot
            die tijd zegt de staat van dienst nog niets.
          </p>
        )}
        <TemplateTable report={perf.live.report} horizon={h} empty="Nog geen live uitkomsten." />
        <IcPerMonth report={perf.live.report} horizon={h} />
        <LetterDetails report={perf.live.report} horizon={h} />
      </section>

      <LearningPanel />

      <section className="card">
        <h2 className="card-title">Voorstellen</h2>
        {(!proposals || proposals.length === 0) && (
          <p className="card-foot muted">Geen voorstellen. Een voorstel ontstaat na een terugtest en in de kwartaalronde.</p>
        )}
        {proposals?.map((p) => <ProposalCard key={p.id} p={p} />)}
      </section>

      <section className="card backtest">
        <h2 className="card-title"><Term id="terugtest">Terugtest</Term></h2>
        <p className="notice backtest-label">{perf.backtest.label}</p>
        {perf.backtest.running && (
          <p className="card-foot">Terugtest {perf.backtest.running.id} loopt sinds {formatDateTime(perf.backtest.running.started_at)}.</p>
        )}
        {perf.backtest.run && (
          <p className="card-foot muted">
            Terugtest {perf.backtest.run.id}: {perf.backtest.run.params.months} maandeinden van{" "}
            {perf.backtest.run.params.start} tot {perf.backtest.run.params.end}, klaar{" "}
            {formatDateTime(perf.backtest.run.finished_at)}. Per maand is het model toegepast met alleen de
            data die aan het eind van die dag bekend was. De lijsten zijn de huidige lijsten: assets die
            sindsdien verdwenen, ontbreken (overlevingsbias).
          </p>
        )}
        <TemplateTable report={perf.backtest.report} horizon={h} empty="Nog geen terugtest gedraaid." />
        <IcPerMonth report={perf.backtest.report} horizon={h} />
        <LetterDetails report={perf.backtest.report} horizon={h} />
      </section>
    </div>
  );
}

function TemplateTable({ report, horizon, empty }: { report: Report | null; horizon: string; empty: string }) {
  const rows = Object.entries(report?.templates ?? {});
  if (rows.length === 0) return <p className="card-foot muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table className="ranking">
        <thead>
          <tr>
            <th scope="col"><Term id="sjabloon">Sjabloon</Term></th>
            <th scope="col" className="num">Maanden</th>
            <th scope="col" className="num">Assets</th>
            <th scope="col">Periode</th>
            <th scope="col" className="num"><Term id="rangcorrelatie">Rangcorrelatie</Term></th>
            <th scope="col" className="num"><Term id="t_waarde">t-waarde</Term></th>
            <th scope="col" className="num">A min F</th>
            <th scope="col">Volgorde A–F</th>
            <th scope="col" className="num"><Term id="grote_misser">Grote missers</Term></th>
            <th scope="col" className="num"><Term id="wisselingen">Wisselingen</Term></th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([id, t]) => {
            const m = t.horizons[horizon];
            return (
              <tr key={id}>
                <td>{t.name_nl}</td>
                <td className="num">{formatNumber(t.coverage.months)}</td>
                <td className="num" title={t.coverage.assets_per_month ? `gemiddeld ${num(t.coverage.assets_per_month)} per maand` : undefined}>
                  {formatNumber(t.coverage.assets)}
                </td>
                <td className="muted">{t.coverage.first?.slice(0, 7)} – {t.coverage.last?.slice(0, 7)}</td>
                <td className="num">{m ? num(m.ic.mean) : "–"}</td>
                <td className="num">{m ? <TValue t={m.ic.t_newey_west} /> : "–"}</td>
                <td className="num">{m?.letters.a_minus_f ? pct(m.letters.a_minus_f.mean) : "–"}</td>
                <td>{m ? orderText(m.letters.order) : "–"}</td>
                <td className="num">{m ? formatNumber(m.letters.big_misses) : "–"}</td>
                <td className="num">{m ? share(m.turnover.letter_changed) : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Rank correlation per month (chapter 8): one bar per month-end, above the line when good scores were
// followed by better returns, below when the order was reversed.
function IcPerMonth({ report, horizon }: { report: Report | null; horizon: string }) {
  const rows = Object.entries(report?.templates ?? {})
    .map(([id, t]) => [id, t.name_nl, Object.entries(t.horizons[horizon]?.ic.by_month ?? {})] as const)
    .filter(([, , months]) => months.length > 0);
  if (rows.length === 0) return null;
  return (
    <details className="details">
      <summary><Term id="rangcorrelatie">Rangcorrelatie</Term> per maand</summary>
      <div className="ic-grid">
        {rows.map(([id, name, months]) => <IcBars key={id} name={name} months={months as [string, number][]} />)}
      </div>
      <p className="muted small">
        Elke staaf is één maandeinde: boven de lijn kregen hoge scores daarna een beter rendement, eronder
        het omgekeerde. Overlappende horizons maken buurmaanden van elkaar afhankelijk.
      </p>
    </details>
  );
}

function IcBars({ name, months }: { name: string; months: [string, number][] }) {
  const w = 320, h = 70, mid = h / 2;
  const step = w / Math.max(months.length, 1);
  const positive = months.filter(([, v]) => v > 0).length;
  return (
    <figure className="ic-figure">
      <figcaption>{name} <span className="muted small">· {positive} van {months.length} maanden boven nul</span></figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} role="img"
        aria-label={`Rangcorrelatie per maand voor ${name}`}>
        <line x1="0" x2={w} y1={mid} y2={mid} className="ic-axis" />
        {months.map(([month, v], i) => {
          const len = Math.min(Math.abs(v), 1) * (mid - 2);
          return (
            <rect key={month} x={i * step} width={Math.max(step - 0.5, 0.5)} y={v >= 0 ? mid - len : mid}
              height={Math.max(len, 0.5)} className={v >= 0 ? "ic-pos" : "ic-neg"}>
              <title>{`${month.slice(0, 7)}: ${numFmt.format(v)}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="ic-range muted small"><span>{months[0][0].slice(0, 7)}</span><span>{months[months.length - 1][0].slice(0, 7)}</span></div>
    </figure>
  );
}

function TValue({ t }: { t: number | null }) {
  if (t === null) return <span className="muted" title="te weinig maanden">–</span>;
  return <span className={Math.abs(t) >= 3 ? "strong" : Math.abs(t) < 2 ? "muted" : undefined}>{num(t)}</span>;
}

function orderText(o: { holds: boolean | null; inversions: number | null }): string {
  if (o.holds === null) return "te weinig letters";
  return o.holds ? "klopt" : `${o.inversions} omkering(en)`;
}

function LetterDetails({ report, horizon }: { report: Report | null; horizon: string }) {
  const rows = Object.entries(report?.templates ?? {}).filter(([, t]) => t.horizons[horizon]);
  if (rows.length === 0) return null;
  return (
    <details className="details">
      <summary>
        <Term id="overrendement">Overrendement</Term> per letter, met 95%-interval (Newey-West)
      </summary>
      {rows.map(([id, t]) => {
        const per = t.horizons[horizon].letters.per_letter;
        return (
          <div key={id} className="table-wrap">
            <h3 className="card-subtitle">{t.name_nl}</h3>
            <table className="ranking">
              <thead>
                <tr>
                  <th scope="col">Letter</th>
                  <th scope="col" className="num">Waarnemingen</th>
                  <th scope="col" className="num">Gemiddeld</th>
                  <th scope="col">95%-interval</th>
                  <th scope="col" className="num">Mediaan</th>
                  <th scope="col" className="num">Versloeg benchmark</th>
                  <th scope="col" className="num">Grootste daling</th>
                </tr>
              </thead>
              <tbody>
                {LETTERS.filter((l) => per[l]).map((l) => (
                  <tr key={l}>
                    <td>{l}</td>
                    <td className="num">{formatNumber(per[l].n)}</td>
                    <td className="num">{pct(per[l].monthly_mean)}</td>
                    <td className="muted">{per[l].ci95 ? `${pct(per[l].ci95[0])} tot ${pct(per[l].ci95[1])}` : "te weinig maanden"}</td>
                    <td className="num">{pct(per[l].median_excess)}</td>
                    <td className="num">{share(per[l].share_beat_benchmark)}</td>
                    <td className="num">{pct(per[l].worst_drawdown)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </details>
  );
}

function ProposalCard({ p }: { p: Proposal }) {
  return (
    <div className="proposal">
      <p>
        <strong>Voorstel {p.id}</strong> · <span className={`status status-${p.status}`}>{STATUS_NL[p.status] ?? p.status}</span>
        <span className="muted"> · {SOURCE_NL[p.source] ?? p.source}</span>
        {p.applied_version && <span className="muted"> · in modelversie {p.applied_version}</span>}
        <span className="muted"> · {formatDateTime(p.created_at)}</span>
      </p>
      <p>{p.summary_nl}</p>
      {p.refusal && p.refusal.length > 0 && (
        <ul className="refusal">{p.refusal.map((r) => <li key={r} className="warn-text small">{r}</li>)}</ul>
      )}
      {p.kind === "letter_scale" && <CalibrationTable evidence={p.evidence as Record<string, CalibrationEntry>} />}
      {p.kind === "weights" && <WeightsTable p={p} />}
      {p.kind === "gate_candidate" && <GateEvidence evidence={p.evidence} />}
      {p.status === "open" && !p.current && (
        <p className="warn-text small">
          Berekend op modelversie {p.model_version}, niet op het actieve model. Goedkeuren kan niet; de volgende
          terugtest van het actieve model maakt een nieuw voorstel. Afwijzen ruimt dit voorstel op.
        </p>
      )}
      {p.status === "open" && !p.current && <ProposalButtons id={p.id} rejectOnly />}
      {p.status === "open" && p.current && (
        <ProposalButtons id={p.id} approveLabel={p.kind === "weights" ? "Goedkeuren en in de schaduw starten" : "Goedkeuren"} />
      )}
      {p.kind === "letter_scale" && p.status === "approved" && !p.applied_version && (
        <p className="muted small">
          Goedgekeurd. De server past het model nooit zelf aan: leg de nieuwe modelversie vast met{" "}
          <code>python -m app.cli apply-proposal {p.id}</code> (zie README) en herstart de server.
        </p>
      )}
      {p.kind === "gate_candidate" && p.status === "approved" && (
        <p className="muted small">Gezien. Een nieuwe harde regel is een modelwijziging: een nieuwe modelversie in de configuratie.</p>
      )}
    </div>
  );
}

function WeightsTable({ p }: { p: Proposal }) {
  const [template, weights] = Object.entries(p.payload as Record<string, Record<string, number>>)[0] ?? [];
  if (!weights) return null;
  const ev = p.evidence as { current?: Record<string, number>; start?: Record<string, number>; bewijs?: string;
    verwacht_effect?: string; risicos?: string; pillars?: Record<string, { ic: number; ic_shrunk: number }> };
  return (
    <div className="table-wrap">
      <table className="ranking">
        <thead>
          <tr>
            <th scope="col">Pijler ({template})</th>
            <th scope="col" className="num">Start</th>
            <th scope="col" className="num">Nu</th>
            <th scope="col" className="num">Voorstel</th>
            <th scope="col" className="num"><Term id="rangcorrelatie">Rangcorrelatie</Term></th>
          </tr>
        </thead>
        <tbody>
          {Object.keys(weights).map((k) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="num">{num(ev.start?.[k])}%</td>
              <td className="num">{num(ev.current?.[k])}%</td>
              <td className="num">{num(weights[k])}%</td>
              <td className="num">{num(ev.pillars?.[k]?.ic)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {ev.bewijs && <p className="small"><strong>Bewijs:</strong> {ev.bewijs}</p>}
      {ev.verwacht_effect && <p className="small"><strong>Verwacht effect:</strong> {ev.verwacht_effect}</p>}
      {ev.risicos && <p className="small"><strong>Risico&apos;s:</strong> {ev.risicos}</p>}
    </div>
  );
}

function GateEvidence({ evidence }: { evidence: Record<string, unknown> }) {
  const toets = evidence.toets as GateTest | null;
  return (
    <div className="small">
      {typeof evidence.verklaring === "string" && <p>{evidence.verklaring}</p>}
      {toets?.best ? (
        <p className="muted">
          Getoetst over de terugtest ({toets.observations} A- en B-grades, {toets.misses} missers): bij drempel{" "}
          {num(toets.best.threshold)} ({toets.best.percentile}e percentiel) {toets.best.misses_caught} missers
          gevangen en {toets.best.false_alarms} keer vals alarm.
        </p>
      ) : <p className="muted">Geen toetsbare kandidaat.</p>}
    </div>
  );
}

function CalibrationTable({ evidence }: { evidence: Record<string, CalibrationEntry> }) {
  const entries = Object.entries(evidence ?? {});
  if (entries.length === 0) return null;
  return (
    <div className="table-wrap">
      <table className="ranking">
        <thead>
          <tr>
            <th scope="col"><Term id="sjabloon">Sjabloon</Term></th>
            <th scope="col" className="num">Maanden</th>
            <th scope="col">Grenzen nu (A/B/C/D)</th>
            <th scope="col">Voorstel</th>
            <th scope="col">Verdeling A/B/C/D/F nu → voorstel</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([id, e]) => (
            <tr key={id}>
              <td>{e.name_nl ?? id}</td>
              <td className="num">{formatNumber(e.months)}</td>
              <td className="muted">{bounds(e.current)}</td>
              <td>{e.proposed ? bounds(e.proposed) : <span className="muted" title={e.reason_nl}>blijft</span>}</td>
              <td className="muted">
                {e.distribution_current && e.distribution_proposed
                  ? `${shares(e.distribution_current)} → ${shares(e.distribution_proposed)}` : e.reason_nl ?? "–"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function bounds(s: Record<string, number>): string {
  return ["A", "B", "C", "D"].map((k) => num(s[k])).join(" / ");
}

function shares(d: Record<string, number>): string {
  return ["A", "B", "C", "D", "F"].map((k) => Math.round((d[k] ?? 0) * 100)).join("/");
}
