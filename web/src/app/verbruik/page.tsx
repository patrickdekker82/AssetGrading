import type { Metadata } from "next";
import { RunJobButton } from "@/components/RunJobButton";
import { fetchServer } from "@/lib/server";
import {
  COUNT_LABELS,
  formatDateTime,
  formatDuration,
  formatNumber,
  PROVIDER_LABELS,
  STATUS_LABELS,
} from "@/lib/format";

export const metadata: Metadata = { title: "Verbruik · Graadmeter" };

type ProviderUsage = {
  provider: string;
  calls: number;
  cost: number;
  errors: number;
  budget: number | null;
  rate_limit: { calls: number; per_seconds: number };
  last_ok: string | null;
  last_error_at: string | null;
  last_error: string | null;
  avg_ms: number | null;
};

type JobRun = {
  id: number;
  job: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  summary: { counts?: Record<string, number>; error_count?: number; errors?: string[] } | null;
  error: string | null;
};

type Jobs = { jobs: { name: string; label_nl: string; next_run: string | null }[]; runs: JobRun[] };

type Coverage = {
  crypto: { list_date: string | null; list_size: number; with_year_eur: number; min_days: number | null; last_day: string | null };
  crypto_assets: { name: string; symbol: string; price_sources: string[] | null; days: number; first_day: string | null }[];
  totals: Record<string, number>;
};

const TRIGGER_LABELS: Record<string, string> = { schedule: "planning", manual: "handmatig", cli: "opdrachtregel" };

export default async function UsagePage() {
  const [usage, jobs, coverage] = await Promise.all([
    fetchServer<{ month: string; providers: ProviderUsage[] }>("/api/usage"),
    fetchServer<Jobs>("/api/jobs"),
    fetchServer<Coverage>("/api/data/coverage"),
  ]);
  if (!usage || !jobs || !coverage) {
    return <p className="notice">De rekenserver is niet bereikbaar. Controleer of alle containers draaien.</p>;
  }
  const labels = Object.fromEntries(jobs.jobs.map((j) => [j.name, j.label_nl]));

  return (
    <section className="stack">
      <div>
        <h1>Bronnen en verbruik</h1>
        <p className="lead">
          Hoeveel aanroepen de app deze maand ({usage.month}) per databron deed, de nachtelijke taken en hoeveel
          data er is. De interface haalt zelf nooit data bij een bron; alles loopt via de rekenserver.
        </p>
      </div>

      <div className="card">
        <h2 className="card-title">Aanroepen per bron</h2>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Bron</th>
                <th scope="col" className="num">Aanroepen</th>
                <th scope="col">Maandbudget</th>
                <th scope="col" className="num">Fouten</th>
                <th scope="col">Laatst gelukt</th>
                <th scope="col" className="num">Gem. duur</th>
                <th scope="col">Snelheidslimiet</th>
              </tr>
            </thead>
            <tbody>
              {usage.providers.map((p) => (
                <tr key={p.provider}>
                  <td>{PROVIDER_LABELS[p.provider] ?? p.provider}</td>
                  <td className="num">{formatNumber(p.calls)}</td>
                  <td><Budget used={p.cost} budget={p.budget} /></td>
                  <td className="num" title={p.last_error ?? undefined}>
                    {p.errors > 0 ? <span className="warn-text">{formatNumber(p.errors)}</span> : "0"}
                  </td>
                  <td>{formatDateTime(p.last_ok)}</td>
                  <td className="num">{p.avg_ms === null ? "–" : `${formatNumber(p.avg_ms)} ms`}</td>
                  <td className="muted">{p.rate_limit.calls} per {p.rate_limit.per_seconds} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="card-foot muted">
          Fouten zijn vaak verwachte zoekpogingen, bijvoorbeeld een munt waarvoor een bron geen gegevens heeft.
          Beweeg over het aantal voor de laatste melding.
        </p>
      </div>

      <div className="card">
        <h2 className="card-title">Nachtelijke taken</h2>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Taak</th>
                <th scope="col">Volgende run</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {jobs.jobs.map((j) => (
                <tr key={j.name}>
                  <td>{j.label_nl}</td>
                  <td>{formatDateTime(j.next_run)}</td>
                  <td className="num"><RunJobButton job={j.name} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3 className="card-subtitle">Laatste runs</h3>
        <div className="table-wrap">
          <table className="ranking">
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">Taak</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">Duur</th>
                <th scope="col">Toegevoegd</th>
              </tr>
            </thead>
            <tbody>
              {jobs.runs.length === 0 && (
                <tr><td colSpan={5} className="muted">Nog geen runs.</td></tr>
              )}
              {jobs.runs.map((r) => (
                <tr key={r.id}>
                  <td>{formatDateTime(r.started_at)} <span className="muted">({TRIGGER_LABELS[r.trigger] ?? r.trigger})</span></td>
                  <td>{labels[r.job] ?? r.job}</td>
                  <td title={r.error ?? r.summary?.errors?.slice(0, 5).join("\n") ?? undefined}>
                    <span className={`status status-${r.status}`}>{STATUS_LABELS[r.status] ?? r.status}</span>
                    {r.summary?.error_count ? <span className="muted"> · {r.summary.error_count} meldingen</span> : null}
                  </td>
                  <td className="num">{formatDuration(r.started_at, r.finished_at)}</td>
                  <td className="muted">{summarise(r.summary?.counts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">Data</h2>
        <div className="stats">
          <Stat label="Crypto in de lijst" value={`${coverage.crypto.with_year_eur} van ${coverage.crypto.list_size}`}
            hint="met minstens één jaar dagkoersen in euro" />
          <Stat label="Laatste dagkoers" value={coverage.crypto.last_day ?? "–"} hint="afgesloten dag (UTC)" />
          <Stat label="Koersen" value={formatNumber(coverage.totals.price_bars)} hint="dagkoersen in totaal" />
          <Stat label="Feiten" value={formatNumber(coverage.totals.facts)} hint="marktwaarde, TVL, on-chain" />
          <Stat label="Wisselkoersen" value={formatNumber(coverage.totals.fx_rates)} hint="ECB-referentiekoersen" />
          <Stat label="Macrowaarden" value={formatNumber(coverage.totals.macro_observations)} hint="FRED-reeksen" />
        </div>
        {coverage.crypto_assets.length > 0 && (
          <details className="details">
            <summary>Dagkoersen per crypto in de lijst ({coverage.crypto.list_date})</summary>
            <div className="table-wrap">
              <table className="ranking">
                <thead>
                  <tr>
                    <th scope="col">Naam</th>
                    <th scope="col">Ticker</th>
                    <th scope="col" className="num">Dagen in euro</th>
                    <th scope="col">Vanaf</th>
                    <th scope="col">Bronnen (voorkeur)</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.crypto_assets.map((a) => (
                    <tr key={a.symbol + a.name}>
                      <td>{a.name}</td>
                      <td>{a.symbol}</td>
                      <td className="num">{a.days < 365 ? <span className="warn-text">{formatNumber(a.days)}</span> : formatNumber(a.days)}</td>
                      <td>{a.first_day ?? "–"}</td>
                      <td className="muted">{(a.price_sources ?? []).map((s) => PROVIDER_LABELS[s] ?? s).join(" → ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}

function Budget({ used, budget }: { used: number; budget: number | null }) {
  if (budget === null) return <span className="muted">geen</span>;
  const pct = Math.min(100, Math.round((used / budget) * 100));
  return (
    <span className="budget" title={`${formatNumber(used)} van ${formatNumber(budget)}`}>
      <span className="budget-bar"><span style={{ width: `${pct}%` }} className={pct > 80 ? "hot" : undefined} /></span>
      <span className="muted">{pct}%</span>
    </span>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-hint muted">{hint}</div>
    </div>
  );
}

function summarise(counts: Record<string, number> | undefined): string {
  if (!counts) return "–";
  const parts = Object.entries(COUNT_LABELS)
    .filter(([key]) => counts[key])
    .map(([key, label]) => `${formatNumber(counts[key])} ${label}`);
  return parts.length ? parts.join(", ") : "niets nieuws";
}
